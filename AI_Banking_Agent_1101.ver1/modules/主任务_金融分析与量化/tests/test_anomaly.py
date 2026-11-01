"""异常识别单元测试：只根据流水判断，不读取标准答案字段。"""

import unittest

from analysis import detect_anomalies


def scenario():
    return {
        "scenario_id": "TEST-ANOMALY",
        "scenario_type": "C",
        "created_at": "2026-10-23T00:00:00",
        "currency": "CNY",
        "accounts": [{"account_id": "ACC1", "balance_minor": 1_000_000}],
        "transactions": [
            {"transaction_id": "S1", "account_id": "ACC1", "date": "2026-10-01",
             "amount_minor": 2_000_000, "transaction_type": "income",
             "category": "工资", "merchant": "示例科技", "status": "booked"},
            # 疑似重复扣款：同商户、同金额、同日期、相差 2 分钟
            {"transaction_id": "D1", "account_id": "ACC1", "date": "2026-10-18",
             "amount_minor": 30_000, "transaction_type": "expense",
             "category": "购物", "merchant": "某电商平台", "time": "10:00:00",
             "status": "booked"},
            {"transaction_id": "D2", "account_id": "ACC1", "date": "2026-10-18",
             "amount_minor": 30_000, "transaction_type": "expense",
             "category": "购物", "merchant": "某电商平台", "time": "10:02:00",
             "status": "booked"},
            # 小额支出（用于平均线）+ 一笔大额异常
            {"transaction_id": "E1", "account_id": "ACC1", "date": "2026-10-05",
             "amount_minor": 10_000, "transaction_type": "expense",
             "category": "餐饮", "merchant": "A店", "status": "booked"},
            {"transaction_id": "E2", "account_id": "ACC1", "date": "2026-10-06",
             "amount_minor": 10_000, "transaction_type": "expense",
             "category": "餐饮", "merchant": "B店", "status": "booked"},
            {"transaction_id": "E3", "account_id": "ACC1", "date": "2026-10-07",
             "amount_minor": 10_000, "transaction_type": "expense",
             "category": "餐饮", "merchant": "C店", "status": "booked"},
            {"transaction_id": "E4", "account_id": "ACC1", "date": "2026-10-08",
             "amount_minor": 10_000, "transaction_type": "expense",
             "category": "餐饮", "merchant": "D店", "status": "booked"},
            {"transaction_id": "E5", "account_id": "ACC1", "date": "2026-10-09",
             "amount_minor": 800_000, "transaction_type": "expense",
             "category": "购物", "merchant": "某奢侈品店", "status": "booked"},
            # 被拒绝的转账
            {"transaction_id": "R1", "account_id": "ACC1", "date": "2026-10-20",
             "amount_minor": 9_000_000, "transaction_type": "transfer_out",
             "category": "转账", "merchant": "张三", "status": "rejected",
             "expected_result": "rejected", "description": "余额不足"},
        ],
        "credit_card_bill": {
            "card_id": "CARD1", "due_date": "2026-10-25", "status": "unpaid",
            "outstanding_amount_minor": 88_000, "items": [],
        },
        "subscriptions": [{
            "subscription_id": "SUB1", "merchant": "某视频平台",
            "amount_minor": 1_990, "cycle": "monthly", "status": "active",
            "next_charge_date": "2026-10-26",
        }],
        "family": [{
            "member_id": "FAM1", "relation": "配偶", "birthday": "2026-11-01",
            "birth_year": 1996, "age_turning": 30,
        }],
        "calendar_events": [
            {"event_id": "EVT-B", "event_type": "birthday", "related_member_id": "FAM1"},
            {"event_id": "EVT-L", "event_type": "budget_lock"},
        ],
        "budget": {"locked_amount_minor": 100_000, "lock_month": "2026-11"},
        "activity_calendar": [{"event_id": "A1"}],
        # 下面这些是标准答案，识别器不应该读取
        "expected_insights": [{"insight_type": "should_not_be_read"}],
    }


class AnomalyTests(unittest.TestCase):
    def setUp(self):
        self.findings = detect_anomalies(scenario())
        self.by_type = {}
        for finding in self.findings:
            self.by_type.setdefault(finding["insight_type"], []).append(finding)

    def test_duplicate_charge(self):
        rows = self.by_type["duplicate_charge"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["severity"], "high")  # 2 分钟内，强重复信号
        self.assertEqual(
            set(rows[0]["evidence_transaction_ids"]), {"D1", "D2"}
        )

    def test_failed_transfer(self):
        rows = self.by_type["failed_transfer"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evidence_transaction_ids"], ["R1"])

    def test_upcoming_bill(self):
        rows = self.by_type["upcoming_bill"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["related_card_id"], "CARD1")
        self.assertEqual(rows[0]["details"]["days_until_due"], 2)

    def test_subscription_renewal(self):
        rows = self.by_type["subscription_renewal"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["details"]["merchant"], "某视频平台")
        self.assertEqual(rows[0]["severity"], "high")  # 3 天内

    def test_birthday(self):
        rows = self.by_type["birthday_upcoming"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["details"]["relation"], "配偶")
        self.assertEqual(rows[0]["related_event_id"], "EVT-B")

    def test_budget_lock(self):
        rows = self.by_type["budget_lock"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["details"]["locked_amount_minor"], 100_000)

    def test_salary(self):
        rows = self.by_type["salary_detected"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evidence_transaction_ids"], ["S1"])

    def test_unusual_spending(self):
        rows = self.by_type["unusual_spending"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evidence_transaction_ids"], ["E5"])

    def test_same_merchant_different_dates_not_duplicate(self):
        data = scenario()
        data["transactions"].append({
            "transaction_id": "D3", "account_id": "ACC1", "date": "2026-10-19",
            "amount_minor": 30_000, "transaction_type": "expense",
            "category": "购物", "merchant": "某电商平台", "time": "10:00:00",
            "status": "booked",
        })
        findings = detect_anomalies(data)
        duplicates = [item for item in findings if item["insight_type"] == "duplicate_charge"]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(set(duplicates[0]["evidence_transaction_ids"]), {"D1", "D2"})

    def test_same_amount_different_merchants_not_duplicate(self):
        data = scenario()
        data["transactions"].append({
            "transaction_id": "D4", "account_id": "ACC1", "date": "2026-10-18",
            "amount_minor": 30_000, "transaction_type": "expense",
            "category": "购物", "merchant": "另一家电商", "time": "10:01:00",
            "status": "booked",
        })
        findings = detect_anomalies(data)
        duplicates = [item for item in findings if item["insight_type"] == "duplicate_charge"]
        self.assertEqual(len(duplicates), 1)
        self.assertNotIn("D4", duplicates[0]["evidence_transaction_ids"])

    def test_does_not_read_expected_answers(self):
        self.assertNotIn("should_not_be_read", self.by_type)

    def test_findings_have_stable_ids(self):
        ids = [finding["finding_id"] for finding in self.findings]
        self.assertEqual(ids, [f"FND-{index:04d}" for index in range(1, len(ids) + 1)])
        self.assertEqual(ids, [finding["finding_id"] for finding in detect_anomalies(scenario())])


if __name__ == "__main__":
    unittest.main()
