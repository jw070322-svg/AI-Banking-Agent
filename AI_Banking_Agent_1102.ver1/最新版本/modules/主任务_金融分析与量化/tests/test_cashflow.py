"""订阅负担与现金流投影的单元测试。"""

import unittest
from datetime import date

from analysis import project_cashflow, subscription_burden


def scenario(
    balance_minor=1_000_000,
    bill_due="2026-10-27",
    bill_outstanding=88_000,
    subscriptions=None,
    activity=None,
    salary=True,
):
    transactions = []
    if salary:
        transactions = [
            {"transaction_id": "SAL-SEP", "account_id": "ACC1", "date": "2026-09-01",
             "amount_minor": 2_000_000, "transaction_type": "income",
             "category": "工资", "merchant": "示例科技", "status": "booked"},
            {"transaction_id": "SAL-OCT", "account_id": "ACC1", "date": "2026-10-01",
             "amount_minor": 2_000_000, "transaction_type": "income",
             "category": "工资", "merchant": "示例科技", "status": "booked"},
        ]

    data = {
        "scenario_id": "TEST-CASHFLOW",
        "scenario_type": "E",
        "created_at": "2026-10-23T00:00:00",
        "currency": "CNY",
        "accounts": [{"account_id": "ACC1", "balance_minor": balance_minor}],
        "transactions": transactions,
        "credit_card_bill": {
            "card_id": "CARD1",
            "due_date": bill_due,
            "status": "unpaid",
            "outstanding_amount_minor": bill_outstanding,
            "items": [],
        },
        "subscriptions": subscriptions if subscriptions is not None else [{
            "subscription_id": "SUB1", "merchant": "某视频平台",
            "amount_minor": 1_990, "cycle": "monthly", "status": "active",
            "next_charge_date": "2026-11-01",
        }],
    }
    if activity is not None:
        data["activity_calendar"] = activity
    return data


class SubscriptionBurdenTests(unittest.TestCase):
    def test_monthly_burden_and_level(self):
        burden = subscription_burden(scenario())
        self.assertEqual(burden["monthly_total_minor"], 1_990)
        self.assertEqual(burden["annual_total_minor"], 23_880)
        self.assertEqual(burden["monthly_income_minor"], 2_000_000)
        self.assertAlmostEqual(burden["burden_ratio"], 0.001, places=4)
        self.assertEqual(burden["burden_level"], "low")

    def test_cycle_is_converted_to_monthly(self):
        data = scenario(subscriptions=[
            {"subscription_id": "S1", "merchant": "季度会员", "amount_minor": 5_970,
             "cycle": "quarterly", "status": "active", "next_charge_date": "2026-11-05"},
            {"subscription_id": "S2", "merchant": "年度会员", "amount_minor": 23_880,
             "cycle": "yearly", "status": "active", "next_charge_date": "2026-12-01"},
        ])
        burden = subscription_burden(data)
        self.assertEqual(burden["monthly_total_minor"], 1_990 + 1_990)
        self.assertEqual(
            [item["monthly_equivalent_minor"] for item in burden["items"]], [1_990, 1_990]
        )

    def test_high_burden_level(self):
        data = scenario(subscriptions=[{
            "subscription_id": "S1", "merchant": "高价会员", "amount_minor": 200_000,
            "cycle": "monthly", "status": "active", "next_charge_date": "2026-11-01",
        }])
        burden = subscription_burden(data)
        self.assertAlmostEqual(burden["burden_ratio"], 0.1, places=4)
        self.assertEqual(burden["burden_level"], "high")

    def test_cancelled_subscription_is_ignored(self):
        data = scenario(subscriptions=[{
            "subscription_id": "S1", "merchant": "已取消", "amount_minor": 50_000,
            "cycle": "monthly", "status": "cancelled", "next_charge_date": "2026-11-01",
        }])
        burden = subscription_burden(data)
        self.assertEqual(burden["active_count"], 0)
        self.assertEqual(burden["monthly_total_minor"], 0)

    def test_no_salary_means_no_ratio(self):
        burden = subscription_burden(scenario(salary=False))
        self.assertIsNone(burden["burden_ratio"])
        self.assertIsNone(burden["burden_level"])


class CashflowProjectionTests(unittest.TestCase):
    def test_thirty_day_projection(self):
        projection = project_cashflow(scenario(), days=30)
        self.assertEqual(projection["starting_balance_minor"], 1_000_000)
        self.assertEqual(projection["expected_income_minor"], 2_000_000)
        self.assertEqual(projection["scheduled_outflow_minor"], 88_000 + 1_990)
        self.assertEqual(projection["ending_balance_minor"], 2_910_010)
        self.assertEqual(projection["lowest_balance_minor"], 910_010)
        self.assertEqual(projection["lowest_balance_date"], "2026-11-01")
        self.assertEqual(projection["shortfall_days"], [])
        self.assertEqual(
            [(event["date"], event["event_type"]) for event in projection["events"]],
            [("2026-10-27", "credit_card"),
             ("2026-11-01", "subscription"),
             ("2026-11-01", "income")],
        )

    def test_ninety_day_projection_repeats_recurring_items(self):
        projection = project_cashflow(scenario(), days=90)
        salaries = [e for e in projection["events"] if e["event_type"] == "income"]
        subscriptions = [e for e in projection["events"] if e["event_type"] == "subscription"]
        self.assertEqual(len(salaries), 3)          # 11-01 / 12-01 / 01-01
        self.assertEqual(len(subscriptions), 3)
        self.assertEqual(projection["expected_income_minor"], 6_000_000)
        self.assertEqual(projection["scheduled_outflow_minor"], 88_000 + 1_990 * 3)

    def test_shortfall_is_reported(self):
        projection = project_cashflow(scenario(balance_minor=50_000), days=30)
        # 10-27 还款后 -38,000；11-01 订阅再扣 1,990 后最低 -39,990
        self.assertEqual(projection["lowest_balance_minor"], -39_990)
        self.assertEqual(projection["shortfall_days"], ["2026-10-27", "2026-11-01"])
        self.assertTrue(any("余额为负" in warning for warning in projection["warnings"]))

    def test_overdue_bill_is_paid_today(self):
        projection = project_cashflow(
            scenario(bill_due="2026-10-20"), days=30
        )
        bill_events = [
            event for event in projection["events"] if event["event_type"] == "credit_card"
        ]
        self.assertEqual(bill_events[0]["date"], "2026-10-23")
        self.assertTrue(any("逾期" in warning for warning in projection["warnings"]))

    def test_bill_outside_horizon_is_ignored(self):
        projection = project_cashflow(
            scenario(bill_due="2026-12-30"), days=30
        )
        self.assertFalse(any(
            event["event_type"] == "credit_card" for event in projection["events"]
        ))

    def test_planned_birthday_activity_is_counted(self):
        projection = project_cashflow(scenario(activity=[
            {"event_id": "A1", "date": "2026-11-05", "title": "预订生日鲜花",
             "category": "鲜花", "budget_minor": 30_000, "status": "planned"},
            {"event_id": "A2", "date": "2026-11-05", "title": "已取消的晚餐",
             "category": "生日晚餐", "budget_minor": 20_000, "status": "cancelled"},
        ]), days=30)
        self.assertEqual(projection["scheduled_outflow_minor"], 88_000 + 1_990 + 30_000)
        self.assertEqual(projection["ending_balance_minor"], 2_880_010)

    def test_no_salary_has_no_income_events(self):
        projection = project_cashflow(scenario(salary=False), days=30)
        self.assertEqual(projection["expected_income_minor"], 0)
        self.assertFalse(any(
            event["event_type"] == "income" for event in projection["events"]
        ))

    def test_days_must_be_in_range(self):
        with self.assertRaises(ValueError):
            project_cashflow(scenario(), days=0)
        with self.assertRaises(ValueError):
            project_cashflow(scenario(), days=367)

    def test_explicit_today_controls_projection(self):
        projection = project_cashflow(
            scenario(), days=30, today=date(2026, 11, 1)
        )
        self.assertEqual(projection["as_of"], "2026-11-01")
        # 12-01 先扣订阅、后发工资，是这 30 天里的最低点
        self.assertEqual(projection["lowest_balance_date"], "2026-12-01")


if __name__ == "__main__":
    unittest.main()
