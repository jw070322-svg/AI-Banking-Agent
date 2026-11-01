"""预算建议回测脚本的单元测试。"""

import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import backtest_budget as bt


def sample_scenario():
    return {
        "scenario_id": "TEST-STRESS",
        "scenario_type": "A",
        "created_at": "2026-10-23T00:00:00",
        "currency": "CNY",
        "accounts": [{"account_id": "ACC1", "balance_minor": 1_000_000}],
        "transactions": [
            {"date": "2026-10-01", "transaction_type": "income",
             "amount_minor": 500_000, "amount": 5000.0, "status": "booked"},
            {"date": "2026-10-05", "transaction_type": "expense",
             "amount_minor": 100_000, "amount": 1000.0, "status": "booked"},
            {"date": "2026-10-06", "transaction_type": "transfer_out",
             "amount_minor": 50_000, "status": "booked"},
        ],
        "credit_card_bill": {
            "items": [{"date": "2026-10-07", "transaction_type": "expense",
                       "amount_minor": 20_000, "amount": 200.0, "status": "booked"}],
            "total_amount_minor": 20_000,
            "paid_amount_minor": 0,
            "outstanding_amount_minor": 20_000,
        },
        "subscriptions": [{"amount_minor": 3_000, "status": "active"}],
        "activity_calendar": [{"budget_minor": 10_000, "date": "2026-10-20"}],
    }


class StressTests(unittest.TestCase):
    def test_stress_does_not_mutate_input(self):
        data = sample_scenario()
        before = copy.deepcopy(data)
        bt.stress_scenario(data, {"name": "combined", "income": 0.8,
                                  "spending": 1.2, "balance": 0.7})
        self.assertEqual(data, before)

    def test_stress_scales_only_target_fields(self):
        data = sample_scenario()
        stressed = bt.stress_scenario(data, {"name": "spending+20%", "income": 1.0,
                                             "spending": 1.2, "balance": 1.0})
        self.assertEqual(stressed["transactions"][0]["amount_minor"], 500_000)
        self.assertEqual(stressed["transactions"][1]["amount_minor"], 120_000)
        # 转账不是消费，不随 spending 缩放
        self.assertEqual(stressed["transactions"][2]["amount_minor"], 50_000)
        self.assertEqual(stressed["accounts"][0]["balance_minor"], 1_000_000)
        self.assertEqual(stressed["credit_card_bill"]["outstanding_amount_minor"], 24_000)
        self.assertEqual(stressed["subscriptions"][0]["amount_minor"], 3_600)
        self.assertEqual(stressed["activity_calendar"][0]["budget_minor"], 12_000)


class BacktestTests(unittest.TestCase):
    def test_single_fixture_invariants(self):
        path = Path(bt.FIXTURE_DIR) / "SCENARIO_A.json"
        result = bt.run_backtest(
            [path], horizons=(30,),
            stress_cases=[bt.STRESS_CASES[0]], policy_grid=[(1, 3)],
        )
        self.assertTrue(result["summary"]["invariants_passed"], result["failures"])
        self.assertEqual(result["summary"]["case_count"], 1)
        self.assertEqual(len(result["baseline"]), 1)
        self.assertEqual(result["baseline"][0]["policy"], {
            "savings_reserve_months": 1, "investment_reserve_months": 3,
        })

    def test_policy_grid_never_makes_investment_more_aggressive(self):
        for savings, investment in bt.POLICY_GRID:
            self.assertGreaterEqual(investment, savings)


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = bt.run_backtest(
            [Path(bt.FIXTURE_DIR) / "SCENARIO_A.json"],
            horizons=(30,),
            stress_cases=[bt.STRESS_CASES[0]],
            policy_grid=[(1, 3)],
        )

    def test_rule_stability_report_has_evidence_sections(self):
        text = bt.render_rule_stability(self.result)
        for keyword in ("规则稳定性", "不变量", "确定性", "压力响应", "复现"):
            self.assertIn(keyword, text)

    def test_data_boundaries_report_has_claim_sections(self):
        text = bt.render_data_boundaries(self.result)
        for keyword in ("可以声明", "不能声明", "比赛六个场景", "真实数据"):
            self.assertIn(keyword, text)

    def test_write_reports_creates_four_files(self):
        with TemporaryDirectory() as temp:
            paths = bt.write_reports(self.result, Path(temp) / "backtest")
            self.assertEqual(len(paths), 4)
            for path in paths:
                self.assertTrue(path.exists(), path)


if __name__ == "__main__":
    unittest.main()
