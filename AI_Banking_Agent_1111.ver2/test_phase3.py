"""Phase 3 测试：filter_candidates 证据回填（G5）、allocate_budget 多品类组合验证
（DESIGN §5）、write_handoff 从 run.jsonl 回填执行字段（R6）。
全部使用合成或已标注来源的本地数据；不是真实端到端验收。"""
import json
import tempfile
import unittest
from pathlib import Path

from schema_check import load_schema, validate
from workflow import allocate_budget, build_plan, filter_candidates, write_handoff

ROOT = Path(__file__).parent


def customer():
    return {"city": "杭州", "special_event": "生日",
            "budget": {"max": "600", "currency": "CNY", "basis": "total"}, "party_size": 4}


def real_quotes():
    data = json.loads((ROOT / "data" / "observed_quotes_20261112.json").read_text(encoding="utf-8-sig"))
    return data["items"]


def cake_item(price_max="80"):
    return {"id": "synthetic-cake-1", "name": "合成蛋糕报价（占位）",
            "price_min": "50", "price_max": price_max, "currency": "CNY", "basis": "total",
            "price_kind": "listed", "source_url": "https://example.com/synthetic-cake-quote",
            "observed_at": "2026-11-12", "synthetic": True}


def synthetic_restaurant(price_min, price_max):
    return {"id": "synthetic-r", "price_min": price_min, "price_max": price_max,
            "currency": "CNY", "basis": "per_person", "price_kind": "listed",
            "source_url": "https://example.com/synthetic", "observed_at": "2026-11-12"}


class FilterEvidenceTests(unittest.TestCase):
    """G5：筛选输出必须携带可审计的价格证据。"""

    def setUp(self):
        self.budget = build_plan(customer())["budget"]

    def test_accepted_record_carries_evidence(self):
        result = filter_candidates(real_quotes(), self.budget, 4)
        # 淀 172×4=688 超界被排除；烛屿 484、山海 488 落入
        self.assertEqual(len(result["candidates"]), 2)
        record = result["candidates"][0]
        for key in ("price_min_cents", "price_max_cents", "basis", "price_kind",
                    "estimated", "source_url", "observed_at", "converted", "name"):
            self.assertIn(key, record, key)
        self.assertTrue(record["estimated"])  # 人均为 average 参考价
        self.assertEqual(record["converted"]["max_cents"], record["price_max_cents"] * 4)

    def test_excluded_carries_price_evidence(self):
        item = dict(real_quotes()[0], price_min="999", price_max="999")
        result = filter_candidates([item], self.budget, 4)
        self.assertEqual(len(result["excluded"]), 1)
        self.assertEqual(result["excluded"][0]["price_min_cents"], 99900)

    def test_unknown_carries_partial_evidence(self):
        item = dict(real_quotes()[0], price_min="100", price_max="200")
        result = filter_candidates([item], self.budget, 4)
        self.assertEqual(len(result["needs_confirmation"]), 1)
        self.assertEqual(result["needs_confirmation"][0]["price_max_cents"], 20000)

    def test_currency_failure_has_no_price_evidence(self):
        item = dict(real_quotes()[0], currency="USD")
        result = filter_candidates([item], self.budget, 4)
        record = result["needs_confirmation"][0]
        self.assertIn("币种", record["reason"])
        self.assertNotIn("price_min_cents", record)


class AllocateBudgetTests(unittest.TestCase):
    """DESIGN §5：组合层验证 餐厅估算+蛋糕+附加费 ≤ 总预算；缺失如实标记。"""

    def setUp(self):
        self.budget = build_plan(customer())["budget"]

    def test_within_budget_with_real_quotes_and_synthetic_cake(self):
        combo = allocate_budget({"餐厅": real_quotes(), "蛋糕": [cake_item()]},
                                self.budget, party_size=4)
        self.assertEqual(combo["verdict"], "within_budget")
        self.assertEqual(combo["combination"]["餐厅"]["name"],
                         "烛屿Candle Island·生日餐厅·约会求婚表白(杭州店)")
        self.assertEqual(combo["best_case_cents"], 48400 + 5000)
        self.assertEqual(combo["worst_case_cents"], 48400 + 8000)
        self.assertEqual(combo["per_category"]["餐厅"]["excluded"], 1)  # 淀 172×4 超界
        self.assertIn("不保证实际结算", combo["notice"])

    def test_partial_overlap(self):
        combo = allocate_budget({"餐厅": [synthetic_restaurant("100", "150")],
                                 "蛋糕": [cake_item(price_max="200")]},
                                self.budget, party_size=4)
        self.assertEqual(combo["verdict"], "partial_overlap_needs_confirmation")
        self.assertEqual(combo["best_case_cents"], 45000)
        self.assertEqual(combo["worst_case_cents"], 80000)

    def test_over_budget(self):
        combo = allocate_budget({"餐厅": [synthetic_restaurant("140", "150")],
                                 "蛋糕": [cake_item()]},
                                self.budget, party_size=4)
        self.assertEqual(combo["verdict"], "over_budget")
        self.assertEqual(combo["best_case_cents"], 61000)

    def test_missing_party_size_flags_not_assumes(self):
        combo = allocate_budget({"餐厅": real_quotes()}, self.budget, party_size=None)
        self.assertEqual(combo["verdict"], "infeasible_with_current_evidence")
        self.assertTrue(any("无可用候选" in i for i in combo["issues"]))
        self.assertEqual(combo["per_category"]["餐厅"]["needs_confirmation"], 3)

    def test_empty_categories(self):
        combo = allocate_budget({}, self.budget)
        self.assertEqual(combo["verdict"], "infeasible_with_current_evidence")
        self.assertTrue(any("未提供任何品类候选" in i for i in combo["issues"]))

    def test_surcharge_pushes_over(self):
        combo = allocate_budget({"餐厅": real_quotes(), "蛋糕": [cake_item()]}, self.budget,
                                party_size=4,
                                known_surcharges=[{"name": "服务费", "amount_cents": 10000}])
        self.assertEqual(combo["verdict"], "over_budget")
        self.assertEqual(combo["surcharges"], [{"name": "服务费", "amount_cents": 10000}])

    def test_bad_surcharge_rejected(self):
        with self.assertRaises(ValueError):
            allocate_budget({"蛋糕": [cake_item()]}, self.budget, party_size=4,
                            known_surcharges=[{"name": "x", "amount_cents": -1}])

    def test_invalid_budget(self):
        with self.assertRaises(ValueError):
            allocate_budget({"蛋糕": [cake_item()]}, None)


class HandoffBackfillTests(unittest.TestCase):
    """R6：交接从 run.jsonl 回填真实执行字段；无日志时如实写 plan_only。"""

    def setUp(self):
        self.plan = build_plan(customer())

    @staticmethod
    def _write_log(path):
        lines = [
            json.dumps({"type": "run_start", "timestamp": "t0", "run_id": "r1",
                        "customer_ref": "synthetic", "mode": "readonly_observation"},
                       ensure_ascii=False),
            json.dumps({"type": "step", "timestamp": "t1", "seq": 1, "action": "open_site",
                        "params": {}, "started_at": "t0", "ended_at": "t1", "duration_ms": 800,
                        "status": "ok", "retries": 0, "error_code": None,
                        "evidence_ref": "evidence/a.png", "response_summary": "官网可达"},
                       ensure_ascii=False),
            json.dumps({"type": "step", "timestamp": "t2", "seq": 2, "action": "select_city",
                        "params": {}, "started_at": "t1", "ended_at": "t2", "duration_ms": 500,
                        "status": "failed", "retries": 1, "error_code": "timeout",
                        "evidence_ref": None, "response_summary": "点击超时"},
                       ensure_ascii=False),
        ]
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_without_log_states_plan_only(self):
        with tempfile.TemporaryDirectory() as temp:
            out = write_handoff(self.plan, temp)
            md = (out / "handoff.md").read_text(encoding="utf-8")
            self.assertIn("执行记录：无（plan_only）", md)
            doc = json.loads((out / "handoff.json").read_text(encoding="utf-8"))
            self.assertNotIn("execution", doc)

    def test_with_log_backfills_steps_and_stays_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "run.jsonl"
            self._write_log(log)
            out = write_handoff(self.plan, temp, execution_log=log)
            md = (out / "handoff.md").read_text(encoding="utf-8")
            self.assertIn("回填自 run.jsonl", md)
            self.assertIn("open_site：ok", md)
            self.assertIn("select_city：failed", md)
            self.assertIn("错误 timeout", md)
            doc = json.loads((out / "handoff.json").read_text(encoding="utf-8"))
            self.assertEqual(len(doc["execution"]["steps"]), 2)
            validate(doc, load_schema("plan.schema.json"))  # 合并后整体仍符合契约

    def test_corrupt_log_line_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "run.jsonl"
            log.write_text('{"type": "step"}\n', encoding="utf-8")  # 缺 timestamp
            with self.assertRaises(ValueError):
                write_handoff(self.plan, temp, execution_log=log)


if __name__ == "__main__":
    unittest.main()
