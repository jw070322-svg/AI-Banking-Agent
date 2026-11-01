"""跨场景流动性测试：锁定生日预算后还能动用多少。"""

import unittest

from analysis import available_liquidity


def scenario(
    balance_minor=500_000,
    locked_minor=100_000,
    lock_month="2026-10",
    activities=None,
    bill_minor=50_000,
    salary=True,
):
    transactions = []
    if salary:
        transactions = [
            {"transaction_id": "SAL-SEP", "account_id": "ACC1", "date": "2026-09-01",
             "amount_minor": 300_000, "transaction_type": "income",
             "category": "工资", "merchant": "示例科技", "status": "booked"},
            {"transaction_id": "SAL-OCT", "account_id": "ACC1", "date": "2026-10-01",
             "amount_minor": 300_000, "transaction_type": "income",
             "category": "工资", "merchant": "示例科技", "status": "booked"},
        ]
    data = {
        "scenario_id": "TEST-LIQUIDITY",
        "scenario_type": "F",
        "created_at": "2026-10-23T00:00:00",
        "currency": "CNY",
        "accounts": [{"account_id": "ACC1", "balance_minor": balance_minor}],
        "transactions": transactions,
        "credit_card_bill": {
            "card_id": "CARD1", "due_date": "2026-10-27", "status": "unpaid",
            "outstanding_amount_minor": bill_minor, "items": [],
        },
    }
    if locked_minor:
        data["budget"] = {
            "locked_amount_minor": locked_minor,
            "lock_month": lock_month,
            "monthly_activity_budget_minor": locked_minor,
        }
    if activities is not None:
        data["activity_calendar"] = activities
    return data


PLANNED = [
    {"event_id": "A1", "date": "2026-10-31", "title": "预订生日鲜花",
     "category": "鲜花", "budget_minor": 30_000, "status": "planned"},
    {"event_id": "A2", "date": "2026-10-31", "title": "预订生日蛋糕",
     "category": "蛋糕", "budget_minor": 30_000, "status": "planned"},
]


class LiquidityTests(unittest.TestCase):
    def test_locked_budget_reduces_available_cash(self):
        result = available_liquidity(scenario(activities=PLANNED))
        self.assertEqual(result["locked_amount_minor"], 100_000)
        self.assertEqual(result["planned_activity_minor"], 60_000)
        self.assertEqual(result["reserved_remaining_minor"], 40_000)
        self.assertEqual(result["minimum_balance_minor"], 390_000)
        self.assertEqual(result["buffer_after_reserve_minor"], 350_000)
        self.assertEqual(result["safe_to_spend_now_minor"], 350_000)
        self.assertEqual(result["safe_to_spend_horizon_minor"], 350_000)
        self.assertEqual(result["locked_amount_at_risk_minor"], 0)

    def test_lock_is_at_risk_when_balance_is_low(self):
        result = available_liquidity(scenario(balance_minor=120_000, activities=PLANNED))
        self.assertEqual(result["minimum_balance_minor"], 10_000)
        self.assertEqual(result["reserved_remaining_minor"], 40_000)
        self.assertEqual(result["locked_amount_at_risk_minor"], 30_000)
        self.assertEqual(result["safe_to_spend_now_minor"], 0)
        self.assertEqual(result["safe_to_spend_horizon_minor"], 0)
        self.assertTrue(any("被占用" in warning for warning in result["warnings"]))

    def test_no_budget_means_all_balance_is_available(self):
        result = available_liquidity(scenario(locked_minor=0, activities=[]))
        self.assertEqual(result["locked_amount_minor"], 0)
        self.assertEqual(result["reserved_remaining_minor"], 0)
        self.assertEqual(result["safe_to_spend_now_minor"], 450_000)
        self.assertEqual(result["safe_to_spend_horizon_minor"], 450_000)

    def test_full_lock_without_planned_spending(self):
        result = available_liquidity(scenario(activities=[]))
        self.assertEqual(result["reserved_remaining_minor"], 100_000)
        # 最低余额 500,000 - 50,000（还款）= 450,000，再留出 100,000 锁定
        self.assertEqual(result["safe_to_spend_horizon_minor"], 350_000)

    def test_future_salary_is_not_counted_as_available_now(self):
        activities = [{
            "event_id": "A3", "date": "2026-11-05", "title": "生日晚餐",
            "category": "生日晚餐", "budget_minor": 350_000, "status": "planned",
        }]
        result = available_liquidity(scenario(
            balance_minor=100_000, locked_minor=0, bill_minor=0, activities=activities,
        ))
        self.assertEqual(result["safe_to_spend_now_minor"], 100_000)
        self.assertEqual(result["safe_to_spend_horizon_minor"], 50_000)

    def test_cancelled_activity_is_not_reserved(self):
        activities = [
            {"event_id": "A1", "date": "2026-10-31", "title": "已取消的晚餐",
             "category": "生日晚餐", "budget_minor": 60_000, "status": "cancelled"},
        ]
        result = available_liquidity(scenario(activities=activities))
        self.assertEqual(result["planned_activity_minor"], 0)
        self.assertEqual(result["reserved_remaining_minor"], 100_000)

    def test_expired_lock_month_releases_reserve(self):
        result = available_liquidity(scenario(lock_month="2026-09", activities=[]))
        self.assertFalse(result["lock_active"])
        self.assertEqual(result["reserved_remaining_minor"], 0)
        self.assertEqual(result["locked_amount_at_risk_minor"], 0)
        self.assertEqual(result["safe_to_spend_now_minor"], 450_000)

    def test_shortfall_is_reported_together_with_lock_risk(self):
        result = available_liquidity(scenario(
            balance_minor=50_000, activities=PLANNED, bill_minor=50_000,
        ))
        self.assertIn("2026-10-31", result["shortfall_days"])
        self.assertGreater(result["locked_amount_at_risk_minor"], 0)
        self.assertTrue(any("余额为负" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
