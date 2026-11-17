import json
import unittest
from pathlib import Path

from schema_check import SchemaValidationError, load_schema, validate
from workflow import build_plan, filter_candidates

ROOT = Path(__file__).parent


def customer():
    return {"city": "杭州", "special_event": "生日",
            "budget": {"max": "600", "currency": "CNY", "basis": "total"}, "party_size": 4}


def item():
    return {"id": "synthetic-1", "price_min": "150", "price_max": "150", "currency": "CNY",
            "basis": "per_person", "price_kind": "average",
            "source_url": "https://example.com/synthetic", "observed_at": "2026-11-11"}


class ValidatorTests(unittest.TestCase):
    def test_example_customer_matches_contract(self):
        data = json.loads((ROOT / "example_customer.json").read_text(encoding="utf-8-sig"))
        validate(data, load_schema("customer_input.schema.json"))

    def test_customer_bad_city_type_rejected(self):
        bad = customer()
        bad["city"] = 7
        with self.assertRaises(SchemaValidationError):
            validate(bad, load_schema("customer_input.schema.json"))

    def test_customer_bad_basis_enum_rejected(self):
        bad = customer()
        bad["budget"]["basis"] = "每人"
        with self.assertRaises(SchemaValidationError):
            validate(bad, load_schema("customer_input.schema.json"))


class PlanContractTests(unittest.TestCase):
    def test_planned_plan_is_valid(self):
        plan = build_plan(customer())
        validate(plan, load_schema("plan.schema.json"))
        self.assertEqual(plan["status"], "planned")
        self.assertFalse(plan["live_executed"])

    def test_needs_input_plan_is_valid(self):
        bad = customer()
        bad.pop("city")
        plan = build_plan(bad)
        validate(plan, load_schema("plan.schema.json"))
        self.assertEqual(plan["status"], "needs_input")
        # 各字段独立校验：城市缺失不影响预算换算结果
        self.assertEqual(plan["budget"]["max_cents"], 60000)

    def test_needs_input_plan_null_budget_is_valid(self):
        bad = customer()
        bad["budget"].pop("basis")
        plan = build_plan(bad)
        validate(plan, load_schema("plan.schema.json"))
        self.assertEqual(plan["status"], "needs_input")
        self.assertEqual(plan["budget"], None)

    def test_plan_rejects_live_executed_true(self):
        plan = build_plan(customer())
        plan["live_executed"] = True
        with self.assertRaises(SchemaValidationError):
            validate(plan, load_schema("plan.schema.json"))

    def test_plan_rejects_extra_field(self):
        plan = build_plan(customer())
        plan["__extra__"] = 1
        with self.assertRaises(SchemaValidationError):
            validate(plan, load_schema("plan.schema.json"))

    def test_plan_rejects_bad_status(self):
        plan = build_plan(customer())
        plan["status"] = "done"
        with self.assertRaises(SchemaValidationError):
            validate(plan, load_schema("plan.schema.json"))

    def test_plan_rejects_unknown_step_action(self):
        plan = build_plan(customer())
        plan["steps"][0]["action"] = "hack_site"
        with self.assertRaises(SchemaValidationError):
            validate(plan, load_schema("plan.schema.json"))


class MerchantContractTests(unittest.TestCase):
    def test_valid_item_accepted(self):
        budget = build_plan(customer())["budget"]
        result = filter_candidates([item()], budget, 4)
        self.assertEqual(len(result["candidates"]), 1)

    def test_non_string_price_is_structural_failure(self):
        budget = build_plan(customer())["budget"]
        bad = item()
        bad["price_min"] = 150
        result = filter_candidates([bad], budget, 4)
        self.assertEqual(len(result["needs_confirmation"]), 1)
        self.assertIn("结构校验失败", result["needs_confirmation"][0]["reason"])

    def test_bad_money_pattern_is_structural_failure(self):
        budget = build_plan(customer())["budget"]
        bad = item()
        bad["price_min"] = "1.001"
        result = filter_candidates([bad], budget, 4)
        self.assertEqual(len(result["needs_confirmation"]), 1)

    def test_currency_mismatch_is_semantic_failure(self):
        budget = build_plan(customer())["budget"]
        bad = item()
        bad["currency"] = "USD"
        result = filter_candidates([bad], budget, 4)
        self.assertEqual(len(result["needs_confirmation"]), 1)
        self.assertIn("币种", result["needs_confirmation"][0]["reason"])

    def test_unknown_basis_is_structural_failure(self):
        budget = build_plan(customer())["budget"]
        bad = item()
        bad["basis"] = "每人"
        result = filter_candidates([bad], budget, 4)
        self.assertEqual(len(result["needs_confirmation"]), 1)


class ForwardContractTests(unittest.TestCase):
    def test_qwen_output_contract(self):
        schema = load_schema("qwen_output.schema.json")
        valid = {"service_categories": ["生日餐厅"], "public_keywords": ["生日餐厅"],
                 "constraints": [], "needs_clarification": False, "evidence_spans": ["生日"]}
        validate(valid, schema)
        valid["__extra__"] = 1
        with self.assertRaises(SchemaValidationError):
            validate(valid, schema)

    def test_trajectory_contract(self):
        schema = load_schema("trajectory.schema.json")
        valid = {"record_id": "synthetic-traj-1", "source_kind": "synthetic",
                 "desensitized": True, "review_status": "pending",
                 "model_version": "qwen2.5-0.5b-instruct-q4_k_m",
                 "template_version": "unverified", "page_version": "unobserved",
                 "evidence_hashes": [], "customer_ref": "synthetic-cust-1"}
        validate(valid, schema)
        valid["source_kind"] = "real"
        with self.assertRaises(SchemaValidationError):
            validate(valid, schema)

    def test_execution_log_contract(self):
        schema = load_schema("execution_log.schema.json")
        run_start = {"type": "run_start", "timestamp": "2026-11-12T00:00:00+08:00",
                     "run_id": "r1", "customer_ref": "synthetic-cust-1", "mode": "plan_only"}
        step = {"type": "step", "timestamp": "2026-11-12T00:00:01+08:00", "run_id": "r1",
                "seq": 1, "action": "open_site", "params": {"url": "https://www.dianping.com/"},
                "status": "ok", "retries": 0, "error_code": None, "evidence_ref": None,
                "duration_ms": 120, "response_summary": "官网可达",
                "started_at": "2026-11-12T00:00:00+08:00", "ended_at": "2026-11-12T00:00:01+08:00"}
        validate(run_start, schema)
        validate(step, schema)
        step["type"] = "other"
        with self.assertRaises(SchemaValidationError):
            validate(step, schema)


if __name__ == "__main__":
    unittest.main()
