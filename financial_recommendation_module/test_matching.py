"""Behavioral checks for the financial matching prototype.

These tests use fictional fixtures. They verify eligibility boundaries,
abstention, preference evidence, and determinism; they do not validate legal
compliance, future returns, or real-world recommendation quality.

Run from this directory: python -m unittest -v test_matching.py
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import unittest

from matching_core import (
    evaluate_eligibility,
    profile_errors,
    sample_history,
    sample_products,
    sample_users,
    validate_catalog,
    validate_top_k,
)
import rule_driven
import data_driven


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.user = sample_users()[0]
        self.product = sample_products()[1]

    def test_exact_boundaries_are_eligible(self):
        user = dict(self.user, risk_tolerance=2, risk_capacity=2,
                    budget_cny=1000, horizon_days=92, max_redemption_days=2)
        self.assertTrue(evaluate_eligibility(user, self.product)["eligible"])

    def test_each_bound_is_binding(self):
        baseline = dict(self.user, risk_tolerance=2, risk_capacity=2,
                        budget_cny=1000, horizon_days=92, max_redemption_days=2)
        for change in ({"risk_capacity": 1}, {"risk_tolerance": 1},
                       {"budget_cny": 999.99}, {"horizon_days": 91},
                       {"max_redemption_days": 1}):
            with self.subTest(change=change):
                self.assertFalse(evaluate_eligibility(dict(baseline, **change),
                                                       self.product)["eligible"])

    def test_conflicting_risk_signals_use_lower_value(self):
        user = dict(self.user, risk_tolerance=5, risk_capacity=1, objective="growth")
        gate = evaluate_eligibility(user, self.product)
        self.assertEqual(gate["effective_risk"], 1)
        self.assertFalse(gate["eligible"])
        self.assertTrue(gate["warnings"])

    def test_missing_critical_profile_is_not_imputed(self):
        for field in ("risk_tolerance", "risk_capacity", "budget_cny",
                      "horizon_days", "max_redemption_days", "objective"):
            with self.subTest(field=field):
                user = deepcopy(self.user)
                del user[field]
                self.assertTrue(profile_errors(user))
                self.assertFalse(evaluate_eligibility(user, self.product)["eligible"])

    def test_malformed_numeric_profile_values_fail_closed(self):
        for field in ("risk_tolerance", "risk_capacity", "budget_cny",
                      "horizon_days", "max_redemption_days"):
            for value in (True, False, None, "3", float("nan"),
                          float("inf"), -1, []):
                with self.subTest(field=field, value=repr(value)):
                    self.assertFalse(evaluate_eligibility(
                        dict(self.user, **{field: value}), self.product)["eligible"])

    def test_malformed_product_values_fail_closed(self):
        for field in ("risk_level", "min_investment_cny", "lockup_days",
                      "redemption_days", "annual_fee_pct"):
            for value in (True, False, "1", float("nan"), float("inf"), -1):
                with self.subTest(field=field, value=repr(value)):
                    self.assertFalse(evaluate_eligibility(
                        self.user, dict(self.product, **{field: value}))["eligible"])

    def test_missing_or_unverified_product_facts_fail_closed(self):
        for change in ({"active": False}, {"active": 1}, {"facts_verified": False},
                       {"facts_verified": 1}, {"currency": "USD"},
                       {"objectives": []}, {"category": "unknown"}):
            with self.subTest(change=change):
                self.assertFalse(evaluate_eligibility(
                    self.user, dict(self.product, **change))["eligible"])

    def test_optional_fee_and_categories_do_not_imply_zero_fee_or_preference(self):
        user = deepcopy(self.user)
        del user["preferred_categories"]
        product = deepcopy(self.product)
        del product["annual_fee_pct"]
        gate = evaluate_eligibility(user, product)
        self.assertTrue(gate["eligible"])
        self.assertEqual(len(gate["warnings"]), 2)

    def test_zero_horizon_admits_only_immediate_access(self):
        user = dict(self.user, horizon_days=0, max_redemption_days=0)
        product = dict(self.product, lockup_days=0, redemption_days=0)
        self.assertTrue(evaluate_eligibility(user, product)["eligible"])
        self.assertFalse(evaluate_eligibility(
            user, dict(product, redemption_days=1))["eligible"])

    def test_ambiguous_catalog_identity_is_rejected(self):
        for products in (None, {}, [None], [{"product_id": " "}],
                         [self.product, deepcopy(self.product)]):
            with self.subTest(products=products):
                with self.assertRaises(ValueError):
                    validate_catalog(products)

    def test_top_k_must_be_positive_integer(self):
        for value in (None, True, False, 0, -1, 1.0, "3"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_top_k(value)
        validate_top_k(1)


class RuleMatcherTests(unittest.TestCase):
    def setUp(self):
        self.user = sample_users()[0]
        self.products = sample_products()

    def test_recommendations_all_pass_shared_gate(self):
        by_id = {p["product_id"]: p for p in self.products}
        for user in sample_users():
            with self.subTest(user_id=user["user_id"]):
                result = rule_driven.recommend(user, self.products, top_k=100)
                for item in result["recommendations"]:
                    self.assertTrue(evaluate_eligibility(user, by_id[item["product_id"]])["eligible"])
                    self.assertTrue(0 <= item["score"] <= 100)

    def test_incomplete_profile_abstains(self):
        result = rule_driven.recommend(sample_users()[3], self.products)
        self.assertEqual(result["status"], "needs_profile_completion")
        self.assertEqual(result["recommendations"], [])

    def test_empty_or_ineligible_catalog_abstains(self):
        for products in ([], [self.products[-1]]):
            result = rule_driven.recommend(self.user, products)
            self.assertEqual(result["status"], "no_eligible_products")
            self.assertEqual(result["recommendations"], [])

    def test_missing_fee_cannot_earn_low_fee_bonus(self):
        baseline = self.products[1]
        known = rule_driven.recommend(self.user, [baseline])["recommendations"][0]
        missing = rule_driven.recommend(self.user, [dict(baseline, annual_fee_pct=None)])["recommendations"][0]
        self.assertEqual(known["score"] - missing["score"], 5)

    def test_objective_priority_dominates_all_lower_preferences(self):
        # Maximize the distractor's category, flexibility and fee preferences.
        objective = dict(self.products[1], product_id="OBJ", category="balanced",
                         lockup_days=400, redemption_days=0, annual_fee_pct=2)
        distractor = dict(self.products[1], product_id="OTHER", objectives=["growth"],
                          lockup_days=0, redemption_days=0, annual_fee_pct=0)
        result = rule_driven.recommend(self.user, [distractor, objective])
        self.assertEqual(result["recommendations"][0]["product_id"], "OBJ")

    def test_ties_use_product_identifier_not_input_order(self):
        first = dict(self.products[1], product_id="A")
        second = dict(self.products[1], product_id="B")
        forward = rule_driven.recommend(self.user, [first, second])
        reverse = rule_driven.recommend(self.user, [second, first])
        self.assertEqual(forward, reverse)
        self.assertEqual([r["product_id"] for r in forward["recommendations"]], ["A", "B"])

    def test_scoring_and_evidence_preserve_inputs(self):
        original = deepcopy((self.user, self.products))
        result = rule_driven.recommend(self.user, self.products)
        self.assertEqual((self.user, self.products), original)
        for item in result["recommendations"]:
            self.assertAlmostEqual(item["score"], sum(
                rule["contribution"] for rule in item["rule_evidence"]))
        json.dumps(result, allow_nan=False)

    def test_no_objective_match_is_explicit(self):
        result = rule_driven.recommend(sample_users()[4], self.products)
        self.assertEqual([r["product_id"] for r in result["recommendations"]], ["P001"])
        self.assertFalse(result["recommendations"][0]["objective_match"])
        self.assertTrue(any("No eligible product matches" in w for w in result["warnings"]))


class DataMatcherTests(unittest.TestCase):
    def setUp(self):
        self.user = sample_users()[0]
        base = sample_products()[1]
        self.products = [dict(base, product_id="A"), dict(base, product_id="B")]
        self.peers = [dict(self.user, user_id="PEER1"), dict(self.user, user_id="PEER2")]
        self.history = [
            {"user_id": peer["user_id"], "product_id": product, "rating": rating}
            for peer in self.peers for product, rating in (("A", 5), ("B", 1))
        ]

    def recommend(self, **changes):
        args = {"user": self.user, "products": self.products,
                "history": self.history, "reference_users": self.peers}
        args.update(changes)
        return data_driven.recommend(**args)

    def test_observed_ratings_change_product_rank(self):
        initial = self.recommend()
        changed = [dict(row, rating=6-row["rating"]) for row in self.history]
        updated = self.recommend(history=changed)
        self.assertEqual(initial["status"], "ok")
        self.assertEqual([r["product_id"] for r in initial["recommendations"]], ["A", "B"])
        self.assertEqual([r["product_id"] for r in updated["recommendations"]], ["B", "A"])
        self.assertEqual(initial["recommendations"][0]["preference_score"], 5)

    def test_no_history_does_not_silently_inject_demo_evidence(self):
        result = data_driven.recommend(self.user, self.products)
        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["evidence"]["training_interactions"], 0)

    def test_one_distinct_peer_is_insufficient(self):
        result = self.recommend(history=self.history[:2], reference_users=self.peers[:1])
        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["recommendations"], [])

    def test_own_history_cannot_leak_into_prediction(self):
        own_rows = [{"user_id": self.user["user_id"], "product_id": "A", "rating": 1},
                    {"user_id": self.user["user_id"], "product_id": "B", "rating": 5}]
        without = self.recommend()
        with_own = self.recommend(history=self.history + own_rows,
                                  reference_users=self.peers + [self.user])
        self.assertEqual(without["recommendations"], with_own["recommendations"])
        self.assertEqual(with_own["evidence"]["training_interactions"], 4)
        self.assertNotIn(self.user["user_id"], with_own["evidence"]["selected_neighbor_ids"])

    def test_feature_ranges_exclude_held_out_target_profile(self):
        extreme_target = dict(self.user, budget_cny=1e10, horizon_days=100000)
        own = {"user_id": self.user["user_id"], "product_id": "A", "rating": 5}
        model = data_driven.NeighborRatingModel().fit(
            self.peers + [extreme_target], self.products, self.history + [own],
            target_user_id=self.user["user_id"])
        # Both remaining peer profiles are identical: no fitted numeric range.
        self.assertEqual(model.ranges, {})

    def test_high_ratings_cannot_override_factual_gate(self):
        user = dict(self.user, risk_capacity=1, risk_tolerance=5, objective="growth")
        result = self.recommend(user=user)
        self.assertEqual(result["status"], "no_eligible_products")
        self.assertEqual(result["recommendations"], [])

    def test_every_sample_recommendation_is_eligible_and_supported(self):
        users, products, history = sample_users(), sample_products(), sample_history()
        by_id = {p["product_id"]: p for p in products}
        for user in users:
            with self.subTest(user_id=user["user_id"]):
                result = data_driven.recommend(user, products, history, users, top_k=100)
                for item in result["recommendations"]:
                    self.assertTrue(evaluate_eligibility(user, by_id[item["product_id"]])["eligible"])
                    self.assertGreaterEqual(item["support_count"], 2)
                    self.assertTrue(1 <= item["preference_score"] <= 5)
                json.dumps(result, allow_nan=False)

    def test_incomplete_target_abstains(self):
        result = self.recommend(user=dict(self.user, risk_capacity=None))
        self.assertEqual(result["status"], "needs_profile_completion")
        self.assertEqual(result["recommendations"], [])

    def test_incomplete_peer_is_skipped_without_imputation(self):
        peers = [self.peers[0], dict(self.peers[1], risk_capacity=None)]
        result = self.recommend(reference_users=peers)
        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["evidence"]["training_users"], 1)
        self.assertTrue(any("PEER2" in warning for warning in result["warnings"]))

    def test_tied_ratings_have_deterministic_product_order(self):
        ratings = [dict(row, rating=4) for row in self.history]
        forward = self.recommend(history=ratings)
        reverse = self.recommend(history=list(reversed(ratings)),
                                 reference_users=list(reversed(self.peers)),
                                 products=list(reversed(self.products)))
        self.assertEqual(forward["recommendations"], reverse["recommendations"])
        self.assertEqual([r["product_id"] for r in forward["recommendations"]], ["A", "B"])

    def test_invalid_or_ambiguous_history_fails_explicitly(self):
        for value in (None, True, "5", float("nan"), float("inf"), 0, 6):
            with self.subTest(rating=repr(value)):
                rows = [dict(self.history[0], rating=value)] + self.history[1:]
                with self.assertRaises(ValueError):
                    self.recommend(history=rows)
        for rows in (self.history + [self.history[0]],
                     [dict(self.history[0], user_id="UNKNOWN")],
                     [dict(self.history[0], product_id="UNKNOWN")]):
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):
                    self.recommend(history=rows)
        with self.assertRaises(ValueError):
            self.recommend(reference_users=self.peers + [self.peers[0]])

    def test_recommend_preserves_caller_records(self):
        original = deepcopy((self.user, self.products, self.history, self.peers))
        self.recommend()
        self.assertEqual((self.user, self.products, self.history, self.peers), original)

    def test_holdout_reports_coverage_with_error(self):
        result = data_driven.evaluate_holdout(sample_users(), sample_products(), sample_history())
        self.assertLessEqual(result["predicted_heldout_rows"], result["eligible_heldout_rows"])
        self.assertTrue(0 <= result["prediction_coverage"] <= 1)
        self.assertTrue(0 <= result["mean_absolute_error_rating_units"] <= 4)
        empty = data_driven.evaluate_holdout(sample_users(), sample_products(), [])
        self.assertIsNone(empty["prediction_coverage"])
        self.assertIsNone(empty["mean_absolute_error_rating_units"])


if __name__ == "__main__":
    unittest.main()
