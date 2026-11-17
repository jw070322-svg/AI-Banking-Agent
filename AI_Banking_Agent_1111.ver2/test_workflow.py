import copy
import json
import tempfile
import unittest
from pathlib import Path
from workflow import build_plan, cents, filter_candidates, write_handoff

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.customer = {"city":"杭州", "special_event":"生日", "budget":{"max":"600","currency":"CNY","basis":"total"}, "party_size":4}
        self.item = {"id":"synthetic-1", "price_min":"150", "price_max":"150", "currency":"CNY", "basis":"per_person", "price_kind":"average", "source_url":"https://example.com/synthetic", "observed_at":"2026-11-11"}
    def test_plan_uses_customer_city(self):
        self.assertEqual(build_plan(self.customer)["city"], "杭州")
    def test_missing_city(self):
        self.customer.pop("city")
        self.assertEqual(build_plan(self.customer)["status"], "needs_input")
    def test_ambiguous_budget(self):
        self.customer["budget"].pop("basis")
        self.assertEqual(build_plan(self.customer)["status"], "needs_input")
    def test_unknown_event(self):
        self.customer["special_event"] = "特殊需求"
        self.assertEqual(build_plan(self.customer)["status"], "needs_input")
    def test_device_not_customer_location(self):
        self.customer["location_mode"] = "device"
        self.assertEqual(build_plan(self.customer)["status"], "needs_input")
    def test_budget_boundary(self):
        budget = build_plan(self.customer)["budget"]
        self.assertEqual(len(filter_candidates([self.item], budget, 4)["candidates"]), 1)
        self.item["price_min"] = self.item["price_max"] = "150.01"
        self.assertEqual(len(filter_candidates([self.item], budget, 4)["excluded"]), 1)
    def test_missing_party_size(self):
        self.assertEqual(len(filter_candidates([self.item], build_plan(self.customer)["budget"])["needs_confirmation"]),1)
    def test_price_interval_partial_overlap(self):
        self.item["price_max"] = "200"
        self.assertEqual(len(filter_candidates([self.item], build_plan(self.customer)["budget"],4)["needs_confirmation"]),1)
    def test_unknown_price(self):
        self.item.pop("price_max")
        self.assertEqual(len(filter_candidates([self.item], build_plan(self.customer)["budget"],4)["needs_confirmation"]),1)
    def test_conditional_price(self):
        self.item["conditional"] = True
        self.assertEqual(len(filter_candidates([self.item], build_plan(self.customer)["budget"],4)["needs_confirmation"]),1)
    def test_bad_money(self):
        for value in ["NaN", "Infinity", "-1", "1.001", True, None]:
            with self.assertRaises(ValueError): cents(value)
    def test_handoff_avoids_raw_event_and_is_unique(self):
        self.customer["special_event"] = "李某生日 电话13812345678"
        plan = build_plan(self.customer)
        with tempfile.TemporaryDirectory() as temp:
            first, second = write_handoff(plan,temp), write_handoff(plan,temp)
            self.assertNotEqual(first,second)
            text = (first / "handoff.json").read_text(encoding="utf-8")
            self.assertNotIn("13812345678",text)
            self.assertFalse(json.loads(text)["live_executed"])

if __name__ == "__main__": unittest.main()
