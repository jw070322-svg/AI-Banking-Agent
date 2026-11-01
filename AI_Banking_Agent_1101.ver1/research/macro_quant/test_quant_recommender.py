"""Independent contract and numerical property tests for the research prototype."""
from __future__ import annotations

import copy
import json
import math
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_recommender import load_json, recommend, weighted_cvar, weighted_var
from reproduce import make_demo

ROOT = Path(__file__).resolve().parent


def scores(result: dict) -> dict:
    return {row["product_id"]: row["score"] for row in result["evaluated"]}


def excluded_ids(result: dict) -> set:
    return {row["product_id"] for row in result["excluded"]}


class CvarTests(unittest.TestCase):
    def test_var_equal_weight_atom_boundary(self):
        self.assertEqual(weighted_var(list(range(1, 11)), [0.1]*10, 0.9), 9.0)

    def test_fractional_boundary_atom(self):
        self.assertAlmostEqual(weighted_cvar([0.10, 0.02, -0.01], [0.05, 0.15, 0.80], 0.90), 0.06, places=13)

    def test_negative_tail_loss_is_not_clipped(self):
        self.assertAlmostEqual(weighted_cvar([-0.01, -0.02], [0.5, 0.5], 0.9), -0.01, places=13)

    def test_constant_loss_and_zero_probability(self):
        self.assertAlmostEqual(weighted_cvar([100.0, 0.03, 0.03], [0.0, 0.4, 0.6], 0.95), 0.03, places=13)

    def test_against_independent_rockafellar_uryasev_breakpoints(self):
        rng = random.Random(20261024)
        for _ in range(80):
            n = rng.randrange(2, 15)
            losses = [rng.choice([-0.06, -0.01, 0.0, 0.02, 0.10]) for _ in range(n)]
            masses = [rng.uniform(0.1, 2.0) for _ in range(n)]
            p = [mass / math.fsum(masses) for mass in masses]
            alpha = rng.choice([0.1, 0.5, 0.8, 0.9, 0.99])
            reference = min(eta + math.fsum(w * max(loss-eta, 0.0) for loss, w in zip(losses, p)) / (1-alpha)
                            for eta in set(losses))
            with self.subTest(losses=losses, alpha=alpha):
                self.assertAlmostEqual(weighted_cvar(losses, p, alpha), reference, places=12)

    def test_invalid_alpha(self):
        for alpha in (0, 1, -0.1, 1.1, True, float("nan"), float("inf")):
            with self.subTest(alpha=alpha), self.assertRaises(ValueError):
                weighted_cvar([0.0, 0.1], [0.5, 0.5], alpha)

    def test_invalid_loss_or_probability(self):
        cases = [([], []), ([0.1], [0.4, 0.6]), ([0.1, 0.2], [-0.1, 1.1]),
                 ([0.1, 0.2], [0.0, 0.0]), ([float("nan")], [1.0]),
                 ([0.1], [float("inf")]), ([True], [1.0]), ([0.1], [True])]
        for losses, p in cases:
            with self.subTest(losses=losses, p=p), self.assertRaises(ValueError):
                weighted_cvar(losses, p, 0.9)


class RecommendationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_config = load_json(ROOT / "params.json")
        cls.base_data = make_demo(cls.base_config)
        cls.base_result = recommend(cls.base_data, cls.base_config)
        if cls.base_result["status"] == "abstain":
            raise AssertionError(f"The deterministic fixture must support scoring: {cls.base_result['reason_codes']}")

    def setUp(self):
        self.data = copy.deepcopy(self.base_data)
        self.config = copy.deepcopy(self.base_config)

    def run_model(self):
        return recommend(self.data, self.config)

    def assert_scores_almost_equal(self, left, right):
        a, b = scores(left), scores(right)
        self.assertEqual(set(a), set(b))
        for pid in a:
            self.assertAlmostEqual(a[pid], b[pid], places=12, msg=pid)

    def test_probability_normalization_and_ess(self):
        result = self.run_model()
        weights = result["diagnostics"]["weights"]
        p, q = [w["weight"] for w in weights], [w["kernel_weight"] for w in weights]
        self.assertAlmostEqual(math.fsum(p), 1.0, places=13)
        self.assertAlmostEqual(math.fsum(q), 1.0, places=13)
        self.assertTrue(all(math.isfinite(x) and x >= 0 for x in p+q))
        self.assertAlmostEqual(result["diagnostics"]["kernel_ess"], 1/math.fsum(x*x for x in q), places=10)
        self.assertAlmostEqual(result["diagnostics"]["mixed_ess"], 1/math.fsum(x*x for x in p), places=10)

    def test_repeat_is_deterministic_and_inputs_immutable(self):
        before_data, before_config = copy.deepcopy(self.data), copy.deepcopy(self.config)
        first, second = self.run_model(), self.run_model()
        self.assertEqual(first, second)
        self.assertEqual(self.data, before_data)
        self.assertEqual(self.config, before_config)
        self.assertTrue(first["research_only"])
        self.assertFalse(first["ledger_modified"])

    def test_future_current_feature_abstains(self):
        future = datetime.fromisoformat(self.data["as_of"]) + timedelta(seconds=1)
        self.data["current_features"]["cpi_yoy"]["available_at"] = future.isoformat()
        result = self.run_model()
        self.assertEqual(result["status"], "abstain")
        self.assertEqual(result["ranking"], [])

    def test_missing_current_feature_abstains(self):
        del self.data["current_features"]["gdp_yoy"]
        self.assertEqual(self.run_model()["status"], "abstain")

    def test_stale_current_feature_abstains(self):
        obs = self.data["current_features"]["term_spread"]
        obs["observation_end"] = (datetime.fromisoformat(self.data["as_of"])-timedelta(days=100)).isoformat()
        self.assertEqual(self.run_model()["status"], "abstain")

    def test_future_label_does_not_influence_scores(self):
        row = self.data["history"][-1]
        row["label_available_at"] = (datetime.fromisoformat(self.data["as_of"])+timedelta(days=1)).isoformat()
        row["product_returns"]["SYN_A"] = 100.0
        expected_data = copy.deepcopy(self.data)
        expected_data["history"].pop()
        actual = self.run_model()
        expected = recommend(expected_data, self.config)
        self.assert_scores_almost_equal(actual, expected)
        self.assertNotIn(row["scenario_id"], actual["diagnostics"]["scenario_ids"])

    def test_future_historical_feature_excludes_whole_row(self):
        row = self.data["history"][-3]
        row["features"]["policy_rate"]["available_at"] = (datetime.fromisoformat(row["decision_at"])+timedelta(seconds=1)).isoformat()
        result = self.run_model()
        self.assertNotIn(row["scenario_id"], result["diagnostics"]["scenario_ids"])

    def test_overlapping_completed_horizons_abstain(self):
        extra = copy.deepcopy(self.data["history"][-3])
        extra["scenario_id"] = "OVERLAP"
        for key in ("decision_at", "label_end", "label_available_at"):
            extra[key] = (datetime.fromisoformat(extra[key])+timedelta(days=1)).isoformat()
        self.data["history"].append(extra)
        self.assertEqual(self.run_model()["status"], "abstain")

    def test_all_features_constant_abstains(self):
        for key in self.config["feature_definitions"]:
            for row in self.data["history"]:
                row["features"][key]["value"] = 0.01
            self.data["current_features"][key]["value"] = 0.01
        self.assertEqual(self.run_model()["status"], "abstain")

    def test_constant_training_feature_shift_abstains(self):
        for row in self.data["history"]:
            row["features"]["policy_rate"]["value"] = 0.02
        self.data["current_features"]["policy_rate"]["value"] = 0.01
        self.assertEqual(self.run_model()["status"], "abstain")

    def test_unchanged_constant_feature_is_removed(self):
        for row in self.data["history"]:
            row["features"]["policy_rate"]["value"] = 0.02
        self.data["current_features"]["policy_rate"]["value"] = 0.02
        result = self.run_model()
        self.assertNotEqual(result["status"], "abstain")
        self.assertIn("policy_rate", result["diagnostics"]["constant_features"])
        self.assertNotIn("policy_rate", result["diagnostics"]["active_features"])

    def test_risk_gate_and_long_horizon_gate(self):
        result = self.run_model()
        self.assertIn("SYN_D", excluded_ids(result))
        self.assertIn("SYN_LOCKED", excluded_ids(result))
        self.assertNotIn("SYN_D", scores(result))
        self.assertNotIn("SYN_LOCKED", scores(result))

    def test_budget_gate_cannot_be_overridden_by_return(self):
        self.data["profile"]["budget_minor"] = 9999
        for row in self.data["history"]:
            row["product_returns"]["SYN_A"] = 100.0
        result = self.run_model()
        self.assertEqual(result["ranking"], [])
        self.assertIn("SYN_A", excluded_ids(result))

    def test_user_redemption_limit_is_hard(self):
        self.data["profile"]["max_redemption_days"] = 1
        result = self.run_model()
        self.assertIn("SYN_B", excluded_ids(result))
        self.assertIn("SYN_C", excluded_ids(result))
        self.assertIn("SYN_A", scores(result))

    def test_user_horizon_is_hard(self):
        self.data["profile"]["horizon_days"] = 1
        result = self.run_model()
        self.assertIn("SYN_B", excluded_ids(result))
        self.assertIn("SYN_A", scores(result))

    def test_missing_product_return_preserves_other_products_support(self):
        del self.data["history"][-3]["product_returns"]["SYN_B"]
        result = self.run_model()
        self.assertIn("SYN_B", excluded_ids(result))
        self.assertEqual(result["diagnostics"]["scenario_ids"], self.base_result["diagnostics"]["scenario_ids"])
        self.assertEqual(result["diagnostics"]["weights"], self.base_result["diagnostics"]["weights"])
        for pid in ("SYN_A", "SYN_C"):
            self.assertAlmostEqual(scores(result)[pid], scores(self.base_result)[pid], places=13)

    def test_historical_universe_membership_is_required(self):
        self.data["history"][-3]["universe"].remove("SYN_B")
        self.assertIn("SYN_B", excluded_ids(self.run_model()))

    def test_historical_return_terms_must_match(self):
        self.data["history"][-3]["product_terms"]["SYN_A"]["redemption_days"] = 2
        self.assertIn("SYN_A", excluded_ids(self.run_model()))

    def test_current_facts_from_future_are_excluded(self):
        self.data["products"][0]["facts_as_of"] = (datetime.fromisoformat(self.data["as_of"])+timedelta(seconds=1)).isoformat()
        self.assertIn("SYN_A", excluded_ids(self.run_model()))

    def test_unverified_point_in_time_abstains(self):
        self.data["provenance"]["point_in_time_verified"] = False
        self.assertEqual(self.run_model()["status"], "abstain")

    def test_different_regime_row_is_excluded(self):
        row = self.data["history"][-3]
        row["regime_id"] = "OTHER_REGIME"
        result = self.run_model()
        self.assertNotIn(row["scenario_id"], result["diagnostics"]["scenario_ids"])

    def test_cost_increase_cannot_raise_score(self):
        self.data["products"][0]["entry_cost_rate"] = 0.001
        self.data["products"][0]["exit_cost_rate"] = 0.002
        self.assertLessEqual(scores(self.run_model())["SYN_A"], scores(self.base_result)["SYN_A"] + 1e-13)

    def test_cash_translation_equivariance_of_score(self):
        shift = 0.013
        for row in self.data["history"]:
            row["product_returns"]["SYN_A"] += shift
        self.assertAlmostEqual(scores(self.run_model())["SYN_A"] - scores(self.base_result)["SYN_A"], shift, places=12)

    def test_scenario_dominance(self):
        source = copy.deepcopy(self.data["products"][0])
        source["product_id"], source["name"] = "DOMINANT", "Dominant test product"
        self.data["products"].append(source)
        for i, row in enumerate(self.data["history"]):
            row["product_returns"]["DOMINANT"] = row["product_returns"]["SYN_A"] + (0.001 if i % 2 else 0.002)
            row["product_terms"]["DOMINANT"] = copy.deepcopy(row["product_terms"]["SYN_A"])
            row["product_costs"]["DOMINANT"] = copy.deepcopy(row["product_costs"]["SYN_A"])
            row["universe"].append("DOMINANT")
        value = scores(self.run_model())
        self.assertGreaterEqual(value["DOMINANT"], value["SYN_A"])

    def test_no_positive_score_uses_cash_option(self):
        for product in self.data["products"]:
            product["entry_cost_rate"] = product["exit_cost_rate"] = 0.0
        for row in self.data["history"]:
            for pid in row["product_returns"]:
                row["product_returns"][pid] = row["cash_return"] - 0.02
        result = self.run_model()
        self.assertEqual(result["status"], "no_positive_score")
        self.assertEqual(result["ranking"], [])
        self.assertTrue(all(row["score"] < 0 for row in result["evaluated"]))

    def test_uniform_baseline_weights_and_same_support(self):
        self.config["model_params"]["weight_mode"] = "uniform"
        result = self.run_model()
        rows = result["diagnostics"]["weights"]
        self.assertEqual(result["diagnostics"]["scenario_ids"], self.base_result["diagnostics"]["scenario_ids"])
        for row in rows:
            self.assertAlmostEqual(row["weight"], 1/len(rows), places=13)

    def test_uniform_mixture_cannot_rescue_kernel_support(self):
        self.config["model_params"]["uniform_mixture"] = 0.999
        self.config["model_params"]["min_kernel_ess"] = 10000.0
        self.assertEqual(self.run_model()["status"], "abstain")

    def test_boolean_budget_and_nonfinite_feature_rejected(self):
        self.data["profile"]["budget_minor"] = True
        with self.assertRaises(ValueError):
            self.run_model()
        self.data = copy.deepcopy(self.base_data)
        self.data["current_features"]["gdp_yoy"]["value"] = float("nan")
        with self.assertRaises(ValueError):
            self.run_model()

    def test_invalid_fee_and_config_rejected(self):
        self.data["products"][0]["entry_cost_rate"] = -0.1
        with self.assertRaises(ValueError):
            self.run_model()
        self.data = copy.deepcopy(self.base_data)
        for key, value in (("bandwidth", 0), ("risk_aversion", 1.01), ("cvar_alpha", 1), ("top_k", True)):
            cfg = copy.deepcopy(self.config)
            cfg["model_params"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                recommend(self.data, cfg)

    def test_duplicate_product_and_scenario_ids_rejected(self):
        self.data["products"].append(copy.deepcopy(self.data["products"][0]))
        with self.assertRaises(ValueError):
            self.run_model()
        self.data = copy.deepcopy(self.base_data)
        self.data["history"].append(copy.deepcopy(self.data["history"][-1]))
        with self.assertRaises(ValueError):
            self.run_model()

    def test_equivalent_mixed_timezones_preserve_economics(self):
        zones = [timezone(timedelta(hours=8)), timezone(timedelta(hours=-2))]
        self.data["as_of"] = datetime.fromisoformat(self.data["as_of"]).astimezone(zones[0]).isoformat()
        for i, row in enumerate(self.data["history"]):
            zone = zones[i % 2]
            for key in ("decision_at", "label_end", "label_available_at"):
                row[key] = datetime.fromisoformat(row[key]).astimezone(zone).isoformat()
            for obs in row["features"].values():
                for key in ("available_at", "observation_end"):
                    obs[key] = datetime.fromisoformat(obs[key]).astimezone(zone).isoformat()
        for obs in self.data["current_features"].values():
            for key in ("available_at", "observation_end"):
                obs[key] = datetime.fromisoformat(obs[key]).astimezone(zones[1]).isoformat()
        for product in self.data["products"]:
            product["facts_as_of"] = datetime.fromisoformat(product["facts_as_of"]).astimezone(zones[1]).isoformat()
        result = self.run_model()
        self.assert_scores_almost_equal(result, self.base_result)
        self.assertEqual(result["diagnostics"]["scenario_ids"], self.base_result["diagnostics"]["scenario_ids"])

    def test_tie_break_is_id_order_not_product_input_order(self):
        first = copy.deepcopy(self.data["products"][0])
        second = copy.deepcopy(first)
        first["product_id"], second["product_id"] = "ZZZ", "AAA"
        self.data["products"] = [first, second]
        for row in self.data["history"]:
            for pid in ("AAA", "ZZZ"):
                row["product_returns"][pid] = row["product_returns"]["SYN_A"]
                row["product_terms"][pid] = copy.deepcopy(row["product_terms"]["SYN_A"])
                row["product_costs"][pid] = copy.deepcopy(row["product_costs"]["SYN_A"])
                row["universe"].append(pid)
        result = self.run_model()
        self.assertEqual([row["product_id"] for row in result["ranking"]], ["AAA", "ZZZ"])


class JsonTests(unittest.TestCase):
    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory)/"invalid.json"
            path.write_text('{"x": 1, "x": 2}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_json(path)

    def test_nonstandard_json_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory)/"invalid.json"
            for value in ("NaN", "Infinity", "-Infinity"):
                path.write_text('{"x": '+value+'}', encoding="utf-8")
                with self.subTest(value=value), self.assertRaises(ValueError):
                    load_json(path)

    def test_valid_json_preserves_values(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory)/"valid.json"
            expected = {"label": "中文", "zero": 0, "nested": [1.0, True, None]}
            path.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(load_json(path), expected)


if __name__ == "__main__":
    unittest.main()
