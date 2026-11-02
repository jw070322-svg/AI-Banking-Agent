"""分类/月度/年度汇总的单元测试（金额全部为整数分）。"""

import unittest

from analysis import annual_report, category_breakdown, monthly_report, overall_summary


def sample_scenario():
    return {
        "scenario_id": "TEST-AGG",
        "scenario_type": "A",
        "created_at": "2026-10-23T00:00:00",
        "currency": "CNY",
        "accounts": [{"account_id": "ACC1", "balance_minor": 500_000}],
        "transactions": [
            {"transaction_id": "T1", "account_id": "ACC1", "date": "2026-10-01",
             "amount_minor": 1_000_000, "transaction_type": "income",
             "category": "工资", "merchant": "示例科技", "status": "booked"},
            {"transaction_id": "T2", "account_id": "ACC1", "date": "2026-10-02",
             "amount_minor": 10_000, "transaction_type": "expense",
             "category": "餐饮", "merchant": "某餐厅", "status": "booked"},
            {"transaction_id": "T3", "account_id": "ACC1", "date": "2026-10-03",
             "amount_minor": 20_000, "transaction_type": "expense",
             "category": "购物", "merchant": "某超市", "status": "booked"},
            {"transaction_id": "T4", "account_id": "ACC1", "date": "2026-10-04",
             "amount_minor": 5_000, "transaction_type": "transfer_out",
             "category": "转账", "merchant": "张三", "status": "booked"},
            {"transaction_id": "T5", "account_id": "ACC1", "date": "2026-09-15",
             "amount_minor": 7_000, "transaction_type": "expense",
             "category": "餐饮", "merchant": "某餐厅", "status": "booked"},
            {"transaction_id": "T6", "account_id": "ACC1", "date": "2026-10-05",
             "amount_minor": 9_000, "transaction_type": "expense",
             "category": "购物", "merchant": "被拒商户", "status": "rejected"},
        ],
        "credit_card_bill": {
            "card_id": "CARD1",
            "statement_date": "2026-10-05",
            "due_date": "2026-11-10",
            "status": "unpaid",
            "total_amount_minor": 30_000,
            "paid_amount_minor": 0,
            "outstanding_amount_minor": 30_000,
            "items": [{
                "transaction_id": "CT1", "card_id": "CARD1", "date": "2026-10-10",
                "amount_minor": 30_000, "amount": -30_000, "direction": "debit",
                "transaction_type": "expense", "category": "购物",
                "merchant": "某商场", "status": "booked",
            }],
        },
        "subscriptions": [{
            "subscription_id": "SUB1", "merchant": "某视频平台",
            "amount_minor": 1_990, "cycle": "monthly", "status": "active",
            "next_charge_date": "2026-11-10",
        }],
    }


class AggregateTests(unittest.TestCase):
    def test_monthly_report(self):
        report = monthly_report(sample_scenario(), "2026-10")
        self.assertEqual(report["income_minor"], 1_000_000)
        self.assertEqual(report["spending_minor"], 60_000)   # 10k + 20k + 信用卡 30k
        self.assertEqual(report["transfer_out_minor"], 5_000)  # 转账不是消费
        self.assertEqual(report["net_minor"], 935_000)
        self.assertEqual(report["transaction_count"], 5)      # 已入账 4 笔 + 信用卡 1 笔
        self.assertEqual(report["active_subscriptions_minor"], 1_990)
        self.assertEqual(report["credit_card"]["outstanding_amount_minor"], 30_000)

    def test_rejected_transaction_is_ignored(self):
        report = monthly_report(sample_scenario(), "2026-10")
        categories = {row["category"]: row["spending_minor"] for row in report["categories"]}
        self.assertEqual(categories["购物"], 50_000)  # 信用卡 30k + 借记卡 20k
        self.assertEqual(sum(categories.values()), 60_000)  # 被拒绝的 9k 不计入

    def test_category_share(self):
        categories = {
            row["category"]: row for row in category_breakdown(sample_scenario(), month="2026-10")
        }
        self.assertEqual(categories["购物"]["share_bp"], 8333)
        self.assertEqual(categories["餐饮"]["share_bp"], 1667)

    def test_annual_report(self):
        report = annual_report(sample_scenario(), 2026)
        self.assertEqual(report["spending_minor"], 67_000)  # 10 月 60k + 9 月 7k
        self.assertEqual(report["income_minor"], 1_000_000)
        self.assertEqual(
            [month["month"] for month in report["months"]], ["2026-09", "2026-10"]
        )

    def test_overall_summary(self):
        summary = overall_summary(sample_scenario())
        self.assertEqual(summary["spending_minor"], 67_000)
        self.assertEqual(summary["months"][0]["month"], "2026-09")

    def test_merchant_ranking(self):
        report = monthly_report(sample_scenario(), "2026-10")
        # 某商场 30k 最多，其次某超市 20k、某餐厅 10k；转账不进商户排行
        self.assertEqual(report["top_merchants"][0]["merchant"], "某商场")
        self.assertEqual(report["top_merchants"][0]["spending_minor"], 30_000)
        self.assertNotIn("张三", [row["merchant"] for row in report["top_merchants"]])


if __name__ == "__main__":
    unittest.main()
