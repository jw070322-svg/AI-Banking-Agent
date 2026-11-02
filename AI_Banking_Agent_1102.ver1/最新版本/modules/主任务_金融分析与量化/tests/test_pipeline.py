"""端到端流水线测试：需求 → 环境生成 → 分析。"""

import json
import unittest

from pipeline import format_summary, run_pipeline


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.duplicate = run_pipeline(
            prompt="生成一个疑似重复扣款场景",
            scenario_type="C",
            seed=42,
            reference_date="2026-10-23",
            days=30,
        )
        cls.birthday = run_pipeline(
            prompt="配偶生日，锁定 1000 元预算",
            scenario_type="F",
            seed=42,
            reference_date="2026-10-23",
            days=30,
        )

    def test_pipeline_shape(self):
        result = self.duplicate
        self.assertEqual(result["status"], "succeeded")
        self.assertFalse(result["ledger_modified"])
        self.assertTrue(result["simulated"])
        self.assertIsNone(result["error"])
        for key in (
            "scenario", "period", "summary", "report", "findings",
            "subscription_burden", "cashflow", "liquidity", "budget_advice",
            "warnings",
        ):
            self.assertIn(key, result)
        self.assertIsInstance(
            result["summary"]["safe_to_save_monthly_minor"], int
        )
        self.assertIsInstance(
            result["summary"]["safe_to_invest_monthly_minor"], int
        )

    def test_report_and_findings(self):
        result = self.duplicate
        self.assertEqual(result["period"]["month"], "2026-10")
        self.assertGreater(result["summary"]["spending_minor"], 0)
        types = {finding["insight_type"] for finding in result["findings"]}
        self.assertIn("duplicate_charge", types)
        self.assertEqual(
            result["summary"]["finding_count"], len(result["findings"])
        )

    def test_birthday_liquidity_chain(self):
        result = self.birthday
        self.assertEqual(result["liquidity"]["locked_amount_minor"], 100_000)
        self.assertGreater(result["liquidity"]["planned_activity_minor"], 0)
        self.assertGreaterEqual(result["liquidity"]["safe_to_spend_now_minor"], 0)
        self.assertEqual(result["subscription_burden"]["active_count"], 0)

    def test_evaluation_is_opt_in(self):
        self.assertNotIn("evaluation", self.duplicate)
        evaluated = run_pipeline(
            prompt="生成一个疑似重复扣款场景",
            scenario_type="C",
            seed=42,
            reference_date="2026-10-23",
            include_evaluation=True,
        )
        self.assertIn("evaluation", evaluated)
        self.assertGreaterEqual(evaluated["evaluation"]["summary"]["recall"], 0.95)

    def test_output_is_json_serializable(self):
        payload = json.dumps(self.duplicate, ensure_ascii=False)
        restored = json.loads(payload)
        self.assertEqual(restored["scenario"]["scenario_type"], "C")
        self.assertIsInstance(restored["summary"]["spending_minor"], int)

    def test_format_summary(self):
        text = format_summary(self.duplicate)
        self.assertIn("消费", text)
        self.assertIn("最低余额", text)

    def test_pipeline_accepts_existing_scenario(self):
        from bridge import generate_scenario

        scenario = generate_scenario(
            "普通用户", scenario_type="A", seed=1, reference_date="2026-10-23"
        )
        result = run_pipeline(scenario=scenario, days=60)
        self.assertEqual(result["period"]["horizon_days"], 60)
        self.assertEqual(result["scenario"]["scenario_type"], "A")


if __name__ == "__main__":
    unittest.main()
