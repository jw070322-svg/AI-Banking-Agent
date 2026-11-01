"""预算建议测试：每月可安全储蓄/投资额与约束。"""

import json
import unittest

from analysis import budget_advice


def scenario(
    balance_minor=500_000,
    income_minor=300_000,
    spending_minor=100_000,
    income_category="奖金",
    income_date="2026-10-01",
    bill_minor=0,
    locked_minor=0,
):
    transactions = []
    if income_minor:
        transactions.append({
            "transaction_id": "INC-OCT", "account_id": "ACC1", "date": income_date,
            "amount_minor": income_minor, "transaction_type": "income",
            "category": income_category, "merchant": "示例来源", "status": "booked",
        })
    if spending_minor:
        transactions.append({
            "transaction_id": "EXP-OCT", "account_id": "ACC1", "date": "2026-10-05",
            "amount_minor": spending_minor, "transaction_type": "expense",
            "category": "餐饮", "merchant": "示例餐厅", "status": "booked",
        })
    data = {
        "scenario_id": "TEST-BUDGET",
        "scenario_type": "A",
        "created_at": "2026-10-23T00:00:00",
        "currency": "CNY",
        "accounts": [{"account_id": "ACC1", "balance_minor": balance_minor}],
        "transactions": transactions,
    }
    if bill_minor:
        data["credit_card_bill"] = {
            "card_id": "CARD1", "due_date": "2026-10-27", "status": "unpaid",
            "outstanding_amount_minor": bill_minor, "items": [],
        }
    if locked_minor:
        data["budget"] = {
            "locked_amount_minor": locked_minor,
            "lock_month": "2026-10",
        }
    return data


class BudgetAdviceTests(unittest.TestCase):
    def test_surplus_and_liquidity_constraints(self):
        result = budget_advice(scenario())
        self.assertEqual(result["monthly_income_minor"], 300_000)
        self.assertEqual(result["monthly_spending_minor"], 100_000)
        self.assertEqual(result["monthly_surplus_minor"], 200_000)

        # 储蓄保留 1 个月支出：500,000 - 100,000 = 400,000，结余只有 200,000
        self.assertEqual(result["savings"]["safe_monthly_minor"], 200_000)
        self.assertEqual(result["savings"]["binding_constraint"], "monthly_surplus")
        # 投资保留 3 个月支出：500,000 - 300,000 = 200,000，与结余相同
        self.assertEqual(result["investment"]["safe_monthly_minor"], 200_000)
        self.assertEqual(result["investment"]["binding_constraint"], "both")
        self.assertEqual(result["recommended_action"], "invest")

    def test_salary_from_previous_month_still_counts(self):
        # 模拟 C 场景：9 月工资、10 月支出，不能误判为无收入
        result = budget_advice(scenario(
            income_category="工资", income_date="2026-09-23"
        ))
        self.assertEqual(result["monthly_income_minor"], 300_000)
        self.assertEqual(result["income_source"], "latest_salary")
        self.assertGreater(result["monthly_surplus_minor"], 0)
        self.assertNotEqual(result["recommended_action"], "insufficient_data")

    def test_low_spending_warning(self):
        result = budget_advice(scenario(spending_minor=10_000))
        self.assertTrue(
            any("支出不足收入" in item for item in result["warnings"])
        )

    def test_insufficient_income(self):
        result = budget_advice(scenario(income_minor=0))
        self.assertEqual(result["monthly_surplus_minor"], 0)
        self.assertEqual(result["savings"]["safe_monthly_minor"], 0)
        self.assertEqual(result["investment"]["safe_monthly_minor"], 0)
        self.assertEqual(result["recommended_action"], "insufficient_data")
        self.assertTrue(any("缺少收入数据" in item for item in result["warnings"]))

    def test_cashflow_shortfall_blocks_advice(self):
        result = budget_advice(scenario(balance_minor=50_000, bill_minor=100_000))
        self.assertTrue(result["shortfall_days"])
        self.assertEqual(result["savings"]["safe_monthly_minor"], 0)
        self.assertEqual(result["investment"]["safe_monthly_minor"], 0)
        self.assertEqual(result["recommended_action"], "fix_cashflow")
        self.assertTrue(any("缺口" in item for item in result["warnings"]))

    def test_locked_budget_is_reserved(self):
        result = budget_advice(scenario(locked_minor=100_000))
        self.assertEqual(result["reserved_remaining_minor"], 100_000)
        self.assertEqual(result["buffer_after_reserve_minor"], 400_000)
        # 投资：400,000 - 300,000 = 100,000
        self.assertEqual(result["investment"]["safe_monthly_minor"], 100_000)
        self.assertEqual(
            result["investment"]["binding_constraint"], "liquidity_reserve"
        )

    def test_projection_days_are_scaled_to_one_month(self):
        result = budget_advice(scenario(), days=90)
        # 90 天内可动用 400,000，折算每 30 天为 133,333
        self.assertEqual(result["savings"]["monthly_capacity_minor"], 133_333)
        self.assertEqual(result["savings"]["safe_monthly_minor"], 133_333)
        self.assertEqual(result["investment"]["monthly_capacity_minor"], 66_666)

    def test_negative_spending_does_not_make_reserve_negative(self):
        result = budget_advice(scenario(spending_minor=-50_000))
        self.assertEqual(result["savings"]["reserve_floor_minor"], 0)
        self.assertEqual(result["investment"]["reserve_floor_minor"], 0)

    def test_output_is_integer_json(self):
        result = budget_advice(scenario())
        json.dumps(result, ensure_ascii=False)
        self.assertTrue(result["simulated"])
        self.assertFalse(result["ledger_modified"])
        for key in ("monthly_income_minor", "monthly_surplus_minor"):
            self.assertIsInstance(result[key], int)
        for bucket in ("savings", "investment"):
            for key, value in result[bucket].items():
                if key.endswith("_minor"):
                    self.assertIsInstance(value, int)

    def test_invalid_days(self):
        for days in (0, 367, True, 1.5):
            with self.subTest(days=days):
                with self.assertRaises(ValueError):
                    budget_advice(scenario(), days=days)


if __name__ == "__main__":
    unittest.main()
