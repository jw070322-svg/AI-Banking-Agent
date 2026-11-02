"""scenario_adapter.py 的契约测试。

覆盖 API-CONTRACT(1).md 的关键约束：
- 响应外壳字段齐全；
- 金额是整数分，状态映射为 booked；
- 输出不包含原始个人信息；
- 余额在整数分下精确对账；
- Idempotency-Key 同参数重放、改参冲突；
- 非法输入返回 INVALID_ARGUMENT，校验失败返回 SCENARIO_INVALID。
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import main
import scenario_adapter
from scenario_adapter import handle_generate, reset_idempotency_store

ENVELOPE_KEYS = {"schema_version", "request_id", "status", "data", "error", "trace", "simulated"}

_TEMP_STORE = None


def setUpModule():
    """整套测试使用独立临时 SQLite，避免污染项目 runtime/。"""
    global _TEMP_STORE
    _TEMP_STORE = TemporaryDirectory()
    scenario_adapter.configure_idempotency_store(
        Path(_TEMP_STORE.name) / "idempotency.sqlite3"
    )


def tearDownModule():
    scenario_adapter.configure_idempotency_store(None)
    _TEMP_STORE.cleanup()


def request(prompt, **extra):
    payload = {"prompt": prompt, "seed": 7, "reference_date": "2026-10-23"}
    payload.update(extra)
    return payload


class ContractShapeTests(unittest.TestCase):
    def setUp(self):
        reset_idempotency_store()

    def test_envelope_and_integer_minor(self):
        response = handle_generate(request("生成一个普通银行用户"), idempotency_key="shape-1")
        self.assertEqual(response["status"], "succeeded", response["error"])
        self.assertEqual(set(response), ENVELOPE_KEYS)
        self.assertEqual(response["schema_version"], "1.0.0")
        self.assertTrue(response["simulated"])
        self.assertIsNone(response["error"])

        data = response["data"]
        self.assertFalse(data["ledger_modified"])
        self.assertTrue(data["scenario_id"])
        for transaction in data["transactions"]:
            self.assertIsInstance(transaction["amount_minor"], int)
            self.assertIsInstance(transaction["amount"], int)
            self.assertGreaterEqual(transaction["amount_minor"], 0)
            self.assertIn(transaction["status"], {"booked", "pending", "rejected", "failed", "reversed"})
            self.assertIn(transaction["direction"], {"credit", "debit"})
        for account in data["accounts"]:
            self.assertIsInstance(account["initial_balance_minor"], int)
            self.assertIsInstance(account["balance_minor"], int)

    def test_no_raw_personal_information(self):
        response = handle_generate(request("生成一个普通银行用户"), idempotency_key="pii-1")
        user = response["data"]["user"]
        for forbidden in ("id_number", "phone", "email", "address", "name"):
            self.assertNotIn(forbidden, user)
        for account in response["data"]["accounts"]:
            self.assertNotIn("account_number", account)

    def test_balance_reconciles_in_minor_units(self):
        for scenario_type, prompt in (
            ("A", "生成一个普通银行用户"),
            ("B", "购物支出比上月增加 800 元"),
            ("C", "疑似重复扣款"),
            ("D", "余额不足导致转账失败"),
            ("E", "周期性订阅扣费"),
            ("F", "配偶生日，锁定 1000 元预算"),
            ("G", "信用卡账单和卡片挂失场景"),
        ):
            with self.subTest(scenario_type=scenario_type):
                response = handle_generate(
                    request(prompt), idempotency_key=f"reconcile-{scenario_type}"
                )
                self.assertEqual(response["status"], "succeeded", response["error"])
                data = response["data"]
                for account in data["accounts"]:
                    delta = sum(
                        transaction["amount"]
                        for transaction in data["transactions"]
                        if transaction["account_id"] == account["account_id"]
                        and transaction["status"] == "booked"
                    )
                    self.assertEqual(
                        account["initial_balance_minor"] + delta,
                        account["balance_minor"],
                        f"账户 {account['account_id']} 整数分对账失败",
                    )

    def test_card_bill_calendar_contract_types(self):
        response = handle_generate(
            request("信用卡账单和卡片挂失场景", scenario_type="G"),
            idempotency_key="card-1",
        )
        self.assertEqual(response["status"], "succeeded", response["error"])
        data = response["data"]

        cards = data["cards"]
        self.assertEqual({card["card_type"] for card in cards}, {"debit", "credit"})
        credit = next(card for card in cards if card["card_type"] == "credit")
        for field in ("credit_limit_minor", "used_credit_minor", "available_credit_minor"):
            self.assertIsInstance(credit[field], int)
        self.assertEqual(
            credit["credit_limit_minor"] - credit["used_credit_minor"],
            credit["available_credit_minor"],
        )
        for key, value in credit["transaction_limit_minor"].items():
            self.assertIsInstance(value, int, key)

        bill = data["credit_card_bill"]
        self.assertIsInstance(bill["outstanding_amount_minor"], int)
        self.assertEqual(bill["outstanding_amount_minor"], credit["used_credit_minor"])
        for item in bill["items"]:
            self.assertIsInstance(item["amount"], int)
            self.assertLessEqual(item["amount"], 0)  # 账单支出为负

        self.assertTrue(data["card_events"])
        for event in data["card_events"]:
            for snapshot_name in ("before", "after"):
                snapshot = event[snapshot_name]
                if "credit_limit_minor" in snapshot:
                    self.assertIsInstance(snapshot["credit_limit_minor"], int)

        for event in data["calendar_events"]:
            if "budget_minor" in event:
                self.assertIsInstance(event["budget_minor"], int)

        transaction_ids = {t["transaction_id"] for t in data["transactions"]}
        transaction_ids |= {item["transaction_id"] for item in bill["items"]}
        for insight in data["expected_insights"]:
            for evidence in insight["evidence_transaction_ids"]:
                self.assertIn(evidence, transaction_ids)

    def test_rejected_transfer_is_not_booked_and_not_counted(self):
        response = handle_generate(request("余额不足导致转账失败"), idempotency_key="d-1")
        data = response["data"]
        rejected = [t for t in data["transactions"] if t["status"] == "rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertLess(rejected[0]["amount"], 0)  # 账单视角：转出为负
        self.assertEqual(rejected[0]["expected_result"], "rejected")


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        reset_idempotency_store()

    def test_same_key_same_params_replays_original_response(self):
        payload = request("疑似重复扣款")
        first = handle_generate(payload, idempotency_key="idem-1")
        second = handle_generate(payload, idempotency_key="idem-1")
        self.assertEqual(first, second)

    def test_same_key_different_params_conflicts(self):
        handle_generate(request("疑似重复扣款"), idempotency_key="idem-2")
        conflict = handle_generate(request("余额不足"), idempotency_key="idem-2")
        self.assertEqual(conflict["status"], "rejected")
        self.assertEqual(conflict["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_different_session_cannot_reuse_cached_response(self):
        payload = request("疑似重复扣款")
        first = handle_generate(payload, idempotency_key="idem-3", session_id="s1")
        second = handle_generate(payload, idempotency_key="idem-3", session_id="s2")
        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(second["status"], "succeeded")
        self.assertNotEqual(first["data"]["scenario_id"], second["data"]["scenario_id"])

    def test_store_survives_reconnect(self):
        payload = request("疑似重复扣款")
        first = handle_generate(payload, idempotency_key="restart-1")
        path = Path(_TEMP_STORE.name) / "idempotency.sqlite3"
        # 关闭并重开连接，模拟进程重启
        scenario_adapter.configure_idempotency_store(path)
        second = handle_generate(payload, idempotency_key="restart-1")
        self.assertEqual(first, second)

    def test_conflict_survives_reconnect(self):
        handle_generate(request("疑似重复扣款"), idempotency_key="restart-2")
        path = Path(_TEMP_STORE.name) / "idempotency.sqlite3"
        scenario_adapter.configure_idempotency_store(path)
        conflict = handle_generate(request("余额不足"), idempotency_key="restart-2")
        self.assertEqual(conflict["status"], "rejected")
        self.assertEqual(conflict["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_store_is_a_persistent_file(self):
        handle_generate(request("普通用户"), idempotency_key="restart-3")
        path = Path(_TEMP_STORE.name) / "idempotency.sqlite3"
        self.assertTrue(path.exists())


class InputValidationTests(unittest.TestCase):
    def setUp(self):
        reset_idempotency_store()

    def assert_invalid(self, payload, keyword=None):
        response = handle_generate(payload, idempotency_key="invalid")
        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["error"]["code"], "INVALID_ARGUMENT")
        if keyword:
            self.assertIn(keyword, response["error"]["message"])

    def test_empty_prompt(self):
        self.assert_invalid({"prompt": "   "}, "不能为空")

    def test_prompt_too_long(self):
        self.assert_invalid({"prompt": "场" * 2001}, "2000")

    def test_prompt_not_string(self):
        self.assert_invalid({"prompt": 123}, "字符串")

    def test_bool_seed_rejected(self):
        self.assert_invalid({"prompt": "普通用户", "seed": True}, "seed")

    def test_negative_seed_rejected(self):
        self.assert_invalid({"prompt": "普通用户", "seed": -1}, "seed")

    def test_float_seed_rejected(self):
        self.assert_invalid({"prompt": "普通用户", "seed": 1.5}, "seed")

    def test_unknown_scenario_type_rejected(self):
        self.assert_invalid({"prompt": "普通用户", "scenario_type": "Z"}, "scenario_type")

    def test_invalid_reference_date_rejected(self):
        self.assert_invalid({"prompt": "普通用户", "reference_date": "2026-13-01"}, "reference_date")

    def test_missing_idempotency_key_format_rejected(self):
        response = handle_generate({"prompt": "普通用户"}, idempotency_key="")
        self.assertEqual(response["error"]["code"], "INVALID_ARGUMENT")


class ScenarioSemanticTests(unittest.TestCase):
    def setUp(self):
        reset_idempotency_store()

    def test_shopping_increase_is_800_yuan_in_minor_units(self):
        response = handle_generate(
            request("创建购物支出比上月增加 800 元的场景", scenario_type="B"),
            idempotency_key="b-1",
        )
        self.assertEqual(response["status"], "succeeded", response["error"])
        monthly = {}
        for transaction in response["data"]["transactions"]:
            if (
                transaction["category"] == "购物"
                and transaction["transaction_type"] == "expense"
                and transaction["status"] == "booked"
            ):
                monthly[transaction["date"][:7]] = (
                    monthly.get(transaction["date"][:7], 0) + transaction["amount_minor"]
                )
        months = sorted(monthly)
        self.assertEqual(len(months), 2)
        self.assertEqual(monthly[months[1]] - monthly[months[0]], 80000)

    def test_birthday_calendar_orders_flowers_and_cake_two_days_before(self):
        response = handle_generate(request("配偶生日，锁定 1000 元预算"), idempotency_key="f-1")
        data = response["data"]
        self.assertEqual(response["status"], "succeeded", response["error"])
        birthday = data["family"][0]["birthday"]
        self.assertEqual(data["budget"]["locked_amount_minor"], 100000)
        self.assertEqual(data["budget"]["lock_month"], birthday[:7])

        from datetime import datetime, timedelta
        order_date = (datetime.strptime(birthday, "%Y-%m-%d") - timedelta(days=2)).strftime("%Y-%m-%d")
        categories = {
            entry["category"] for entry in data["activity_calendar"] if entry["date"] == order_date
        }
        self.assertIn("鲜花", categories)
        self.assertIn("蛋糕", categories)
        total = sum(entry["budget_minor"] for entry in data["activity_calendar"])
        self.assertLessEqual(total, data["budget"]["locked_amount_minor"])

    def test_scenario_invalid_when_validation_fails(self):
        broken = {
            "scenario_id": "SCN_BROKEN",
            "scenario_type": "C",
            "scenario_name": "疑似重复扣款",
            "created_at": "2026-10-23T00:00:00",
            "user": {"user_id": "U1"},
            "accounts": [{"account_id": "ACC1", "initial_balance": 100, "balance": 100}],
            "transactions": [
                {"transaction_id": "T1", "account_id": "ACC1", "date": "2026-10-01",
                 "amount": 10, "transaction_type": "expense", "category": "购物"},
            ],
            "scenario_requirements": {"goal": "x", "expected": {}},
        }
        with mock.patch.object(main, "generate_scenario", return_value=broken):
            response = handle_generate({"prompt": "疑似重复扣款"}, idempotency_key="broken-1")
        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["error"]["code"], "SCENARIO_INVALID")
        self.assertIsNone(response["data"])


if __name__ == "__main__":
    unittest.main()
