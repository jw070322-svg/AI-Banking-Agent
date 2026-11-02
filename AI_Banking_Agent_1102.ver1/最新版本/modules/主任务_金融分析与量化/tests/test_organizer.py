"""数据整理 Agent 测试：视图投影、单位、缺失条件与只读约束。"""

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from analysis import load_scenario
from organizer import OrganizerError, organize, write_package
from tools import call_tool

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def fixture(name: str):
    return load_scenario(FIXTURES / f"SCENARIO_{name}.json")


def minimal_scenario(**overrides):
    data = {
        "scenario_id": "TEST-ORGANIZER",
        "scenario_type": "A",
        "created_at": "2026-10-23T00:00:00",
        "currency": "CNY",
        "ledger_modified": False,
        "user": {"user_id": "U-TEST", "profile": {}},
        "accounts": [
            {"account_id": "ACC1", "balance_minor": 500_000, "currency": "CNY"}
        ],
        "transactions": [
            {"transaction_id": "T1", "date": "2026-10-01", "amount_minor": 300_000,
             "transaction_type": "income", "direction": "credit",
             "category": "工资", "status": "booked"},
            {"transaction_id": "T2", "date": "2026-10-05", "amount_minor": 100_000,
             "transaction_type": "expense", "direction": "debit",
             "category": "餐饮", "status": "booked"},
        ],
    }
    data.update(overrides)
    return data


class OrganizerShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = fixture("F")

    def test_package_and_view_shape(self):
        package = organize(self.f)
        self.assertEqual(package["organizer_version"], "1.0.0")
        self.assertFalse(package["manifest"]["ledger_modified"])
        self.assertTrue(package["manifest"]["simulated"])
        self.assertEqual(
            set(package["views"]),
            {"analysis", "recommendation", "cards", "display"},
        )
        self.assertEqual(package["views"]["analysis"]["amount_unit"], "minor")
        self.assertEqual(package["views"]["display"]["amount_unit"], "minor")
        self.assertTrue(package["views"]["display"]["read_only"])

    def test_analysis_view_is_accepted_by_tools(self):
        scenario = organize(self.f)["views"]["analysis"]["scenario"]
        result = call_tool("analysis.pipeline", {"days": 30}, data=scenario)
        self.assertEqual(result["status"], "succeeded", result.get("error"))
        self.assertFalse(result["ledger_modified"])

    def test_input_is_not_mutated(self):
        data = copy.deepcopy(self.f)
        before = json.dumps(data, ensure_ascii=False, sort_keys=True)
        organize(data)
        after = json.dumps(data, ensure_ascii=False, sort_keys=True)
        self.assertEqual(before, after)

    def test_expected_insights_removed_by_default(self):
        data = copy.deepcopy(self.f)
        data["expected_insights"] = [{"title": "SENTINEL-ANSWER"}]
        data["evaluation_only_fields"] = ["expected_insights"]
        package = organize(data)
        raw = json.dumps(package, ensure_ascii=False)
        self.assertNotIn("SENTINEL-ANSWER", raw)
        analysis_scenario = package["views"]["analysis"]["scenario"]
        self.assertNotIn("expected_insights", analysis_scenario)
        self.assertNotIn("evaluation_only_fields", analysis_scenario)
        self.assertFalse(package["manifest"]["evaluation_fields_included"])

    def test_expected_insights_can_be_kept_for_evaluation(self):
        data = copy.deepcopy(self.f)
        data["expected_insights"] = [{"title": "SENTINEL-ANSWER"}]
        package = organize(data, {"include_evaluation": True})
        raw = json.dumps(package, ensure_ascii=False)
        self.assertIn("SENTINEL-ANSWER", raw)
        self.assertTrue(package["manifest"]["evaluation_fields_included"])

    def test_pii_fields_are_removed_and_reported(self):
        data = copy.deepcopy(self.f)
        data["user"]["phone"] = "13800138000"
        data["accounts"][0]["account_number"] = "6222000011112222"
        data["transactions"][0]["id_number"] = "110101199001010000"
        package = organize(data)
        raw = json.dumps(package, ensure_ascii=False)
        for secret in ("13800138000", "6222000011112222", "110101199001010000"):
            self.assertNotIn(secret, raw)
        removed = package["manifest"]["quality"]["pii_fields_removed"]
        self.assertIn("phone", removed)
        self.assertIn("account_number", removed)
        self.assertIn("id_number", removed)


class RecommendationViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = fixture("F")

    def test_budget_is_min_of_configured_and_analysis(self):
        package = organize(self.f, {"configured_amount_minor": 2_000_000})
        view = package["views"]["recommendation"]
        headroom = view["conditions"]["analysis_headroom_minor"]
        self.assertGreater(headroom, 0)
        self.assertEqual(view["conditions"]["budget_minor"], headroom)
        self.assertEqual(view["conditions"]["budget_source"], "min_configured_analysis")
        self.assertEqual(view["profile"]["budget_cny"], round(headroom / 100, 2))
        self.assertIn("CNY yuan", view["money_unit"])

    def test_smaller_configured_amount_wins(self):
        package = organize(self.f, {"configured_amount_minor": 500_000})
        view = package["views"]["recommendation"]
        self.assertEqual(view["conditions"]["budget_minor"], 500_000)
        self.assertEqual(view["profile"]["budget_cny"], 5000.0)

    def test_no_configured_amount_uses_analysis_headroom(self):
        package = organize(self.f)
        view = package["views"]["recommendation"]
        self.assertEqual(
            view["conditions"]["budget_minor"],
            view["conditions"]["analysis_headroom_minor"],
        )
        self.assertEqual(view["conditions"]["budget_source"], "analysis_headroom")

    def test_zero_headroom_falls_back_to_configured(self):
        package = organize(fixture("D"), {"configured_amount_minor": 500_000})
        view = package["views"]["recommendation"]
        self.assertEqual(view["conditions"]["analysis_headroom_minor"], 0)
        self.assertEqual(view["conditions"]["budget_minor"], 500_000)
        self.assertEqual(view["conditions"]["budget_source"], "configured_analysis_zero")

    def test_missing_profile_does_not_invent_risk_tolerance(self):
        package = organize(self.f)
        view = package["views"]["recommendation"]
        self.assertIsNone(view["profile"]["risk_tolerance"])
        self.assertEqual(view["profile"]["risk_capacity"], 1)
        self.assertTrue(
            any("needs_profile_completion" in item for item in view["warnings"])
        )
        self.assertTrue(
            any("risk_capacity" in item for item in view["assumptions"])
        )

    def test_profile_is_passed_through(self):
        context = {
            "profile": {
                "user_id": "U-PROFILE",
                "risk_tolerance": 1,
                "risk_capacity": 1,
                "objective": "income",
                "preferred_categories": ["fixed_income"],
                "max_redemption_days": 1,
            },
            "goal": {"months": 6},
        }
        view = organize(self.f, context)["views"]["recommendation"]
        self.assertEqual(view["profile"]["user_id"], "U-PROFILE")
        self.assertEqual(view["profile"]["risk_tolerance"], 1)
        self.assertEqual(view["profile"]["objective"], "income")
        self.assertEqual(view["profile"]["preferred_categories"], ["fixed_income"])
        self.assertEqual(view["profile"]["horizon_days"], 180)

    def test_invalid_goal_months_falls_back_to_30_days(self):
        view = organize(self.f, {"goal": {"months": 0}})["views"]["recommendation"]
        self.assertEqual(view["profile"]["horizon_days"], 30)
        self.assertTrue(any("goal.months" in item for item in view["warnings"]))

    def test_invalid_configured_amount_is_ignored(self):
        package = organize(self.f, {"configured_amount_minor": -1})
        view = package["views"]["recommendation"]
        self.assertIsNone(view["conditions"]["configured_amount_minor"])
        self.assertTrue(any("configured_amount_minor" in item for item in view["warnings"]))


class CardsAndDisplayTests(unittest.TestCase):
    def test_cards_view_for_g(self):
        view = organize(fixture("G"))["views"]["cards"]
        self.assertTrue(view["available"])
        self.assertTrue(view["cards"])
        self.assertTrue(view["credit_card_bill"])
        self.assertTrue(view["card_events"])

    def test_cards_view_empty_is_marked(self):
        view = organize(minimal_scenario())["views"]["cards"]
        self.assertFalse(view["available"])
        self.assertEqual(set(view["missing"]), {"cards", "credit_card_bill", "card_events"})

    def test_display_view_is_read_only(self):
        view = organize(fixture("F"))["views"]["display"]
        self.assertTrue(view["read_only"])
        self.assertFalse(view["ledger_modified"])
        self.assertEqual(view["currency"], "CNY")
        self.assertIsInstance(view["available_balance_minor"], int)


class InputValidationTests(unittest.TestCase):
    def test_invalid_days(self):
        for days in (0, 367, True, 1.5):
            with self.subTest(days=days):
                with self.assertRaises(OrganizerError):
                    organize(minimal_scenario(), {"days": days})

    def test_invalid_today(self):
        with self.assertRaises(OrganizerError):
            organize(minimal_scenario(), {"today": "2026-13-01"})

    def test_invalid_include_evaluation(self):
        with self.assertRaises(OrganizerError):
            organize(minimal_scenario(), {"include_evaluation": "yes"})

    def test_writable_scenario_is_rejected(self):
        with self.assertRaises(OrganizerError):
            organize(minimal_scenario(ledger_modified=True))


class WriterTests(unittest.TestCase):
    def test_write_package_files(self):
        with TemporaryDirectory() as temp:
            paths = write_package(organize(fixture("F")), temp)
            self.assertEqual(len(paths), 6)
            for path in paths:
                self.assertTrue(path.exists(), path)
                json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
