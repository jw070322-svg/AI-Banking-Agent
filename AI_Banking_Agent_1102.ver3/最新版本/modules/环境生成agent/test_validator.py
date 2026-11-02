"""validator.py 的独立基础测试，可用 python -m unittest -v 运行。"""

import unittest

from validator import validate


def valid_scenario():
    return {
        "scenario_id": "TEST001",
        "scenario_type": "A",
        "user": {"user_id": "USER001"},
        "accounts": [{"account_id": "ACC001", "initial_balance": 1000, "balance": 900}],
        "transactions": [
            {"transaction_id": "T001", "account_id": "ACC001", "amount": 1000,
             "transaction_type": "income", "category": "工资"},
            {"transaction_id": "T002", "account_id": "ACC001", "amount": 1100,
             "transaction_type": "expense", "category": "日常消费"},
        ],
    }


class ValidatorTests(unittest.TestCase):
    def test_valid_scenario_passes(self):
        ok, messages = validate(valid_scenario(), {})
        self.assertTrue(ok, messages)

    def test_missing_accounts_rejected(self):
        scenario = valid_scenario()
        scenario["accounts"] = []
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("accounts" in message for message in messages))

    def test_negative_amount_rejected(self):
        scenario = valid_scenario()
        scenario["transactions"][0]["amount"] = -1
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("不能为负数" in message for message in messages))

    def test_duplicate_transaction_id_rejected(self):
        scenario = valid_scenario()
        scenario["transactions"][1]["transaction_id"] = "T001"
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("交易 ID 重复" in message for message in messages))

    def test_unknown_transaction_type_rejected(self):
        scenario = valid_scenario()
        scenario["transactions"][0]["transaction_type"] = "unknown"
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("transaction_type" in message for message in messages))

    def test_supported_transfer_type_accepted(self):
        scenario = valid_scenario()
        scenario["transactions"][1]["transaction_type"] = "transfer_out"
        ok, messages = validate(scenario, {})
        self.assertTrue(ok, messages)

    def test_incorrect_ending_balance_rejected(self):
        scenario = valid_scenario()
        scenario["accounts"][0]["balance"] = 901
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("余额不一致" in message for message in messages))

    def test_rejected_transfer_does_not_change_balance(self):
        scenario = valid_scenario()
        scenario["transactions"].append({
            "transaction_id": "T003", "account_id": "ACC001", "amount": 5000,
            "transaction_type": "transfer_out", "category": "转账", "status": "rejected",
        })
        ok, messages = validate(scenario, {})
        self.assertTrue(ok, messages)

    @staticmethod
    def shopping_scenario(second_month_total=1000, second_month="2026-02"):
        scenario = valid_scenario()
        scenario["scenario_type"] = "B"
        scenario["transactions"] = [
            {"transaction_id": "TB1", "account_id": "ACC001", "date": "2026-01-10",
             "amount": 200, "transaction_type": "expense", "category": "购物"},
            {"transaction_id": "TB2", "account_id": "ACC001", "date": f"{second_month}-10",
             "amount": second_month_total, "transaction_type": "expense", "category": "购物"},
        ]
        scenario["accounts"][0]["initial_balance"] = 2000
        scenario["accounts"][0]["balance"] = 2000 - 200 - second_month_total
        return scenario

    def test_shopping_increase_is_calculated_from_transactions(self):
        scenario = self.shopping_scenario()
        config = {"params": {"increase_amount": 800}}
        ok, messages = validate(scenario, config)
        self.assertTrue(ok, messages)

    def test_wrong_shopping_increase_rejected(self):
        scenario = self.shopping_scenario(second_month_total=999)
        config = {"params": {"increase_amount": 800}}
        ok, messages = validate(scenario, config)
        self.assertFalse(ok)
        self.assertTrue(any("购物支出差额" in message for message in messages))

    def test_nonconsecutive_shopping_months_rejected(self):
        scenario = self.shopping_scenario(second_month="2026-03")
        config = {"params": {"increase_amount": 800}}
        ok, messages = validate(scenario, config)
        self.assertFalse(ok)
        self.assertTrue(any("连续" in message for message in messages))


class ScenarioCTests(unittest.TestCase):
    """场景 C：疑似重复扣款。"""

    @staticmethod
    def duplicate_scenario():
        scenario = valid_scenario()
        scenario["scenario_type"] = "C"
        scenario["transactions"] = [
            {"transaction_id": "TC0", "account_id": "ACC001", "date": "2026-01-01",
             "amount": 1000, "transaction_type": "income", "category": "工资"},
            {"transaction_id": "TC1", "account_id": "ACC001", "date": "2026-01-05",
             "amount": 100, "transaction_type": "expense", "category": "餐饮",
             "merchant": "某餐厅"},
            {"transaction_id": "TC2", "account_id": "ACC001", "date": "2026-01-10",
             "amount": 200, "transaction_type": "expense", "category": "购物",
             "merchant": "某电商平台", "is_suspicious": True,
             "duplicate_group_id": "DUP1", "related_transaction_id": "TC3"},
            {"transaction_id": "TC3", "account_id": "ACC001", "date": "2026-01-10",
             "amount": 200, "transaction_type": "expense", "category": "购物",
             "merchant": "某电商平台", "is_suspicious": True,
             "duplicate_group_id": "DUP1", "related_transaction_id": "TC2"},
        ]
        scenario["accounts"][0]["initial_balance"] = 1000
        scenario["accounts"][0]["balance"] = 1500
        return scenario

    def test_valid_duplicate_scenario_passes(self):
        ok, messages = validate(self.duplicate_scenario(), {})
        self.assertTrue(ok, messages)

    def test_different_merchant_rejected(self):
        scenario = self.duplicate_scenario()
        scenario["transactions"][3]["merchant"] = "另一个商户"
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("商户不一致" in message for message in messages))

    def test_missing_related_transaction_rejected(self):
        scenario = self.duplicate_scenario()
        del scenario["transactions"][2]["related_transaction_id"]
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("related_transaction_id" in message for message in messages))

    def test_single_member_group_rejected(self):
        scenario = self.duplicate_scenario()
        scenario["transactions"].pop()  # 只剩一笔疑似交易
        scenario["accounts"][0]["balance"] = 1700
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("成员不足 2 笔" in message for message in messages))

    def test_no_normal_transaction_rejected(self):
        scenario = self.duplicate_scenario()
        # 把正常交易也标记成疑似，场景里就没有"非疑似原始交易"了
        for transaction in scenario["transactions"]:
            transaction["is_suspicious"] = True
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("未保留原始正常交易" in message for message in messages))


class ScenarioDTests(unittest.TestCase):
    """场景 D：余额不足。"""

    @staticmethod
    def insufficient_scenario():
        scenario = valid_scenario()
        scenario["scenario_type"] = "D"
        scenario["transactions"] = [
            {"transaction_id": "TD1", "account_id": "ACC001", "date": "2026-01-01",
             "amount": 500, "transaction_type": "income", "category": "工资"},
            {"transaction_id": "TD2", "account_id": "ACC001", "date": "2026-01-05",
             "amount": 300, "transaction_type": "expense", "category": "购物"},
            {"transaction_id": "TD3", "account_id": "ACC001", "date": "2026-01-06",
             "amount": 1200, "transaction_type": "transfer_out", "category": "转账",
             "status": "rejected", "expected_result": "rejected"},
        ]
        scenario["accounts"][0]["initial_balance"] = 500
        scenario["accounts"][0]["balance"] = 700  # 500 + 500 - 300，被拒绝的 1200 不算
        return scenario

    def test_valid_insufficient_balance_passes(self):
        ok, messages = validate(self.insufficient_scenario(), {})
        self.assertTrue(ok, messages)

    def test_transfer_within_balance_rejected(self):
        scenario = self.insufficient_scenario()
        scenario["transactions"][2]["amount"] = 500
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("未超过可用余额" in message for message in messages))

    def test_rejected_transaction_must_be_transfer_out(self):
        scenario = self.insufficient_scenario()
        scenario["transactions"][2]["transaction_type"] = "expense"
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("不是转出转账" in message for message in messages))

    def test_missing_rejected_transaction_rejected(self):
        scenario = self.insufficient_scenario()
        scenario["transactions"].pop()
        scenario["accounts"][0]["balance"] = 700
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("缺少被拒绝的转账请求" in message for message in messages))


class ScenarioETests(unittest.TestCase):
    """场景 E：周期性订阅。"""

    @staticmethod
    def subscription_scenario(dates=("2026-01-15", "2026-02-15", "2026-03-15")):
        scenario = valid_scenario()
        scenario["scenario_type"] = "E"
        transactions = [
            {"transaction_id": "TE0", "account_id": "ACC001", "date": "2026-01-01",
             "amount": 1000, "transaction_type": "income", "category": "工资"},
        ]
        for index, day in enumerate(dates, start=1):
            transactions.append({
                "transaction_id": f"TE{index}", "account_id": "ACC001", "date": day,
                "amount": 15, "transaction_type": "expense", "category": "订阅",
                "merchant": "某视频平台", "subscription_type": "视频会员",
                "subscription_cycle": "monthly", "recurring": True,
            })
        scenario["transactions"] = transactions
        scenario["accounts"][0]["initial_balance"] = 5000
        scenario["accounts"][0]["balance"] = 5000 + 1000 - 15 * len(dates)
        return scenario

    def test_valid_subscription_passes(self):
        ok, messages = validate(self.subscription_scenario(), {})
        self.assertTrue(ok, messages)

    def test_varying_amount_rejected(self):
        scenario = self.subscription_scenario()
        scenario["transactions"][2]["amount"] = 20
        scenario["accounts"][0]["balance"] -= 5
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("金额不一致" in message for message in messages))

    def test_nonconsecutive_months_rejected(self):
        scenario = self.subscription_scenario(dates=("2026-01-15", "2026-03-15"))
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("不连续" in message for message in messages))

    def test_different_day_rejected(self):
        scenario = self.subscription_scenario(dates=("2026-01-15", "2026-02-20", "2026-03-15"))
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("每月同一天" in message for message in messages))

    def test_subscription_without_category_rejected(self):
        scenario = self.subscription_scenario()
        for transaction in scenario["transactions"][1:]:
            transaction["category"] = "娱乐"
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("'订阅'类别" in message for message in messages))


class ScenarioFTests(unittest.TestCase):
    """场景 F：家庭生日跨场景联动。"""

    @staticmethod
    def birthday_scenario():
        scenario = valid_scenario()
        scenario["scenario_type"] = "F"
        scenario["family"] = [
            {"member_id": "FAM1", "relation": "配偶", "birthday": "2026-10-20",
             "birth_year": 1996, "age_turning": 30},
        ]
        scenario["budget"] = {
            "monthly_activity_budget": 1000,
            "locked_amount": 1000,
            "currency": "CNY",
            "lock_month": "2026-10",
        }
        scenario["activity_calendar"] = [
            {"event_id": "EVT1", "date": "2026-10-18", "title": "预订生日鲜花",
             "category": "鲜花", "budget": 300, "status": "planned", "related_member_id": "FAM1"},
            {"event_id": "EVT2", "date": "2026-10-18", "title": "预订生日蛋糕",
             "category": "蛋糕", "budget": 300, "status": "planned", "related_member_id": "FAM1"},
            {"event_id": "EVT3", "date": "2026-10-20", "title": "生日晚餐",
             "category": "生日晚餐", "budget": 300, "status": "planned", "related_member_id": "FAM1"},
        ]
        # 锁定金额必须来自真实可用余额，这里给账户准备充足余额
        scenario["accounts"][0]["initial_balance"] = 5000
        scenario["accounts"][0]["balance"] = 4900
        return scenario

    def test_valid_birthday_scenario_passes(self):
        ok, messages = validate(self.birthday_scenario(), {})
        self.assertTrue(ok, messages)

    def test_missing_cake_order_rejected(self):
        scenario = self.birthday_scenario()
        scenario["activity_calendar"].pop(1)
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("缺少蛋糕" in message for message in messages))

    def test_calendar_over_locked_budget_rejected(self):
        scenario = self.birthday_scenario()
        scenario["activity_calendar"][2]["budget"] = 500
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("超过锁定金额" in message for message in messages))

    def test_birthday_outside_lock_month_rejected(self):
        scenario = self.birthday_scenario()
        scenario["family"][0]["birthday"] = "2026-11-20"
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("不在锁定月份" in message for message in messages))

    def test_wrong_order_date_rejected(self):
        scenario = self.birthday_scenario()
        for entry in scenario["activity_calendar"][:2]:
            entry["date"] = "2026-10-17"  # 应为生日前 2 天 = 10-18
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("缺少鲜花" in message or "缺少蛋糕" in message for message in messages))


class CardAndLifeDataTests(unittest.TestCase):
    """卡片、信用卡账单、日历提醒、智能洞察的通用校验。"""

    @staticmethod
    def g_scenario():
        scenario = valid_scenario()
        scenario["scenario_type"] = "G"
        scenario["transactions"] = [
            {"transaction_id": "TG1", "account_id": "ACC001", "date": "2026-10-01",
             "amount": 1000, "transaction_type": "income", "category": "工资"},
            {"transaction_id": "TG2", "account_id": "ACC001", "date": "2026-10-10",
             "amount": 100, "transaction_type": "expense", "category": "餐饮",
             "merchant": "某餐厅"},
        ]
        scenario["accounts"] = [
            {"account_id": "ACC001", "initial_balance": 5000, "balance": 5900}
        ]
        scenario["cards"] = [
            {"card_id": "CARD_D", "user_id": "USER001", "account_id": "ACC001",
             "card_type": "debit", "card_number_masked": "6222 **** **** 1111",
             "brand": "银联", "status": "active", "currency": "CNY",
             "opened_date": "2024-01-01",
             "transaction_limit": {"daily": 50000, "single": 20000}},
            {"card_id": "CARD_C", "user_id": "USER001", "account_id": "ACC001",
             "card_type": "credit", "card_number_masked": "6225 **** **** 2222",
             "brand": "银联", "status": "active", "currency": "CNY",
             "opened_date": "2024-01-01",
             "credit_limit": 15000, "used_credit": 2000, "available_credit": 13000,
             "statement_day": 2, "due_day": 20,
             "transaction_limit": {"daily": 20000, "single": 10000}},
        ]
        scenario["credit_card_bill"] = {
            "bill_id": "BILL1", "card_id": "CARD_C",
            "cycle_start": "2026-10-03", "statement_date": "2026-11-02",
            "due_date": "2026-11-20",
            "items": [{
                "transaction_id": "CT1", "card_id": "CARD_C", "date": "2026-10-15",
                "amount": 2000, "transaction_type": "expense", "category": "购物",
                "merchant": "某商场", "status": "completed",
            }],
            "total_amount": 2000, "minimum_payment": 200,
            "paid_amount": 0, "outstanding_amount": 2000,
            "status": "unpaid", "currency": "CNY",
        }
        scenario["card_events"] = [{
            "event_id": "CEV1", "card_id": "CARD_C", "date": "2026-11-01",
            "event_type": "limit_adjusted", "status": "completed",
            "before": {"credit_limit": 10000}, "after": {"credit_limit": 15000},
            "reason": "提额",
        }]
        scenario["calendar_events"] = [{
            "event_id": "EVT1", "date": "2026-11-20", "event_type": "bill_due",
            "category": "信用卡还款", "title": "信用卡还款", "related_card_id": "CARD_C",
            "related_member_id": None, "related_subscription_id": None,
            "remind_days_before": 3, "remind_date": "2026-11-17",
            "priority": "high", "budget": 2000, "status": "planned", "notes": "",
        }]
        scenario["expected_insights"] = [{
            "insight_id": "INS1", "insight_type": "upcoming_bill", "severity": "high",
            "title": "信用卡账单待还款", "date": "2026-11-20",
            "evidence_transaction_ids": [], "related_event_id": "EVT1",
            "related_card_id": "CARD_C", "details": {},
        }]
        return scenario

    def test_valid_card_scenario_passes(self):
        ok, messages = validate(self.g_scenario(), {})
        self.assertTrue(ok, messages)

    def test_credit_limit_relation_mismatch_rejected(self):
        scenario = self.g_scenario()
        scenario["cards"][1]["used_credit"] = 3000  # 15000 - 3000 != 13000
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("额度关系不一致" in message for message in messages))

    def test_bill_total_mismatch_rejected(self):
        scenario = self.g_scenario()
        scenario["credit_card_bill"]["total_amount"] = 2100
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("账单合计" in message for message in messages))

    def test_bill_outstanding_must_match_card(self):
        scenario = self.g_scenario()
        scenario["credit_card_bill"]["paid_amount"] = 500
        scenario["credit_card_bill"]["outstanding_amount"] = 1500
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("已用额度" in message for message in messages))

    def test_missing_card_events_rejected(self):
        scenario = self.g_scenario()
        scenario["card_events"] = []
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("缺少卡片管理事件" in message for message in messages))

    def test_card_final_status_must_match_event(self):
        scenario = self.g_scenario()
        scenario["card_events"].append({
            "event_id": "CEV2", "card_id": "CARD_C", "date": "2026-11-02",
            "event_type": "card_frozen", "status": "completed",
            "before": {"status": "active"}, "after": {"status": "frozen"},
            "reason": "冻结",
        })
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("最终状态" in message for message in messages))

    def test_calendar_remind_date_must_be_consistent(self):
        scenario = self.g_scenario()
        scenario["calendar_events"][0]["remind_date"] = "2026-11-18"
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("提醒日期" in message for message in messages))

    def test_insight_evidence_must_exist(self):
        scenario = self.g_scenario()
        scenario["expected_insights"][0]["evidence_transaction_ids"] = ["NOT_EXIST"]
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("不存在的交易" in message for message in messages))

    def test_missing_bill_rejected_for_g(self):
        scenario = self.g_scenario()
        scenario.pop("credit_card_bill")
        ok, messages = validate(scenario, {})
        self.assertFalse(ok)
        self.assertTrue(any("缺少信用卡账单" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
