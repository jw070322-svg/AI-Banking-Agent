"""主 Agent 工具接口测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from bridge import generate_scenario, reset_generation_cache
from tools import call_tool, list_tools


class ToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset_generation_cache()
        cls.scenario = generate_scenario(
            "疑似重复扣款", scenario_type="C", seed=42, reference_date="2026-10-23"
        )

    def test_tool_specs(self):
        names = {spec["name"] for spec in list_tools()}
        self.assertEqual(names, {
            "scenario.generate", "bills.summary", "bills.categories",
            "anomalies.detect", "subscriptions.burden",
            "cashflow.project", "liquidity.available", "budget.advice",
            "analysis.pipeline",
        })
        for spec in list_tools():
            self.assertIn("parameters", spec)
            self.assertTrue(spec["description"])

    def test_unknown_tool(self):
        result = call_tool("nope", {}, data=self.scenario)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error"]["code"], "UNKNOWN_TOOL")

    def test_missing_context(self):
        result = call_tool("anomalies.detect", {})
        self.assertEqual(result["error"]["code"], "MISSING_CONTEXT")

    def test_unknown_argument(self):
        result = call_tool("bills.summary", {"foo": 1}, data=self.scenario)
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_invalid_days(self):
        for days in (0, 367, True, 1.5):
            with self.subTest(days=days):
                result = call_tool("cashflow.project", {"days": days}, data=self.scenario)
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_bills_tools(self):
        monthly = call_tool("bills.summary", {"month": "2026-10"}, data=self.scenario)
        self.assertEqual(monthly["status"], "succeeded")
        self.assertEqual(monthly["data"]["month"], "2026-10")
        yearly = call_tool("bills.summary", {"year": 2026}, data=self.scenario)
        self.assertEqual(yearly["data"]["year"], 2026)
        categories = call_tool("bills.categories", {"month": "2026-10"}, data=self.scenario)
        self.assertTrue(categories["data"])

    def test_analysis_tools(self):
        findings = call_tool("anomalies.detect", {}, data=self.scenario)
        self.assertIn("duplicate_charge", {
            item["insight_type"] for item in findings["data"]
        })
        burden = call_tool("subscriptions.burden", {}, data=self.scenario)
        self.assertIn("monthly_total_minor", burden["data"])
        projection = call_tool("cashflow.project", {"days": 30}, data=self.scenario)
        self.assertEqual(projection["data"]["horizon_days"], 30)
        liquidity = call_tool("liquidity.available", {}, data=self.scenario)
        self.assertIn("safe_to_spend_now_minor", liquidity["data"])
        self.assertNotIn("projection", liquidity["data"])

    def test_pipeline_tool_and_evaluation_flag(self):
        plain = call_tool("analysis.pipeline", {}, data=self.scenario)
        self.assertEqual(plain["status"], "succeeded")
        self.assertNotIn("evaluation", plain["data"])
        evaluated = call_tool(
            "analysis.pipeline", {"include_evaluation": True}, data=self.scenario
        )
        self.assertIn("evaluation", evaluated["data"])
        self.assertFalse(plain["ledger_modified"])

    def test_scenario_generate_tool(self):
        result = call_tool("scenario.generate", {
            "prompt": "普通用户", "scenario_type": "A",
            "seed": 3, "reference_date": "2026-10-23",
        })
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["data"]["scenario_type"], "A")
        self.assertFalse(result["data"]["ledger_modified"])
        # 对客默认输出不能带评测标准答案
        self.assertNotIn("expected_insights", result["data"])
        self.assertNotIn("evaluation_only_fields", result["data"])

    def test_scenario_generate_evaluation_opt_in(self):
        result = call_tool("scenario.generate", {
            "prompt": "普通用户", "scenario_type": "A",
            "seed": 3, "reference_date": "2026-10-23",
            "include_evaluation": True,
        })
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(result["data"]["expected_insights"])
        self.assertEqual(
            result["data"]["evaluation_only_fields"], ["expected_insights"]
        )

    def test_scenario_generate_rejects_non_bool_flag(self):
        result = call_tool("scenario.generate", {
            "prompt": "普通用户", "scenario_type": "A",
            "seed": 3, "reference_date": "2026-10-23",
            "include_evaluation": "yes",
        })
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_budget_advice_tool(self):
        result = call_tool("budget.advice", {"days": 30}, data=self.scenario)
        self.assertEqual(result["status"], "succeeded")
        advice = result["data"]
        self.assertIn("savings", advice)
        self.assertIn("investment", advice)
        self.assertIsInstance(advice["savings"]["safe_monthly_minor"], int)
        self.assertFalse(result["ledger_modified"])

    def test_budget_advice_invalid_days(self):
        result = call_tool("budget.advice", {"days": 0}, data=self.scenario)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_scenario_file_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "scenario.json"
            path.write_text(
                json.dumps(self.scenario, ensure_ascii=False), encoding="utf-8"
            )
            result = call_tool("anomalies.detect", {"scenario_file": str(path)})
            self.assertEqual(result["status"], "succeeded")
            self.assertTrue(result["data"])

    def test_all_results_are_json_serializable(self):
        for spec in list_tools():
            name = spec["name"]
            if name == "scenario.generate":
                continue
            arguments = {"days": 30} if name in (
                "cashflow.project", "liquidity.available", "budget.advice",
                "analysis.pipeline",
            ) else {}
            result = call_tool(name, arguments, data=self.scenario)
            with self.subTest(tool=name):
                self.assertEqual(result["status"], "succeeded", result)
                json.dumps(result, ensure_ascii=False)
                self.assertTrue(result["simulated"])
                self.assertFalse(result["ledger_modified"])


if __name__ == "__main__":
    unittest.main()
