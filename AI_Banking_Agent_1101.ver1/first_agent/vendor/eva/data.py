"""虚拟银行数据 + 内存版核心系统。

所有数据都是程序生成的假数据，仅用于演示流水线，不包含任何真实客户信息。
"""

from __future__ import annotations

import json
import random
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from .models import ToolError, utc_now

CNY = "CNY"
TODAY = date.today()


def D(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _next_month_day(day: int) -> str:
    year, month = TODAY.year, TODAY.month
    if TODAY.day >= day:
        month += 1
        if month > 12:
            year += 1
            month = 1
    return date(year, month, day).isoformat()


CUSTOMERS = {
    "CUST-001": {
        "customer_id": "CUST-001",
        "name": "林知夏",
        "segment": "金卡客户",
        "phone_masked": "138****6721",
        "identity_level": "strong",
    },
    "CUST-002": {
        "customer_id": "CUST-002",
        "name": "周远",
        "segment": "普通客户",
        "phone_masked": "139****2088",
        "identity_level": "strong",
    },
}


ACCOUNTS = {
    "ACC-4821": {
        "account_id": "ACC-4821",
        "customer_id": "CUST-001",
        "type": "储蓄卡",
        "last4": "4821",
        "kind": "debit",
        "currency": CNY,
        "balance": D("128450.32"),
        "available": D("128450.32"),
        "status": "active",
        "opened_at": "2019-04-18",
    },
    "ACC-9077": {
        "account_id": "ACC-9077",
        "customer_id": "CUST-001",
        "type": "工资卡",
        "last4": "9077",
        "kind": "debit",
        "currency": CNY,
        "balance": D("23780.10"),
        "available": D("23780.10"),
        "status": "active",
        "opened_at": "2022-09-01",
    },
    "ACC-3312": {
        "account_id": "ACC-3312",
        "customer_id": "CUST-001",
        "type": "信用卡",
        "last4": "3312",
        "kind": "credit",
        "currency": CNY,
        "credit_limit": D("50000.00"),
        "outstanding": D("12450.00"),
        "available_credit": D("37550.00"),
        "status": "active",
        "opened_at": "2021-06-11",
    },
    # 属于另一位客户，用来演示账户隔离
    "ACC-9999": {
        "account_id": "ACC-9999",
        "customer_id": "CUST-002",
        "type": "储蓄卡",
        "last4": "9999",
        "kind": "debit",
        "currency": CNY,
        "balance": D("50000.00"),
        "available": D("50000.00"),
        "status": "active",
        "opened_at": "2021-03-12",
    },
}


CARDS = {
    "CARD-3312": {
        "card_id": "CARD-3312",
        "customer_id": "CUST-001",
        "account_id": "ACC-3312",
        "type": "信用卡",
        "network": "银联",
        "last4": "3312",
        "status": "active",
    },
    "CARD-4821": {
        "card_id": "CARD-4821",
        "customer_id": "CUST-001",
        "account_id": "ACC-4821",
        "type": "借记卡",
        "network": "银联",
        "last4": "4821",
        "status": "active",
    },
}


BENEFICIARIES = {
    "BEN-001": {
        "beneficiary_id": "BEN-001",
        "customer_id": "CUST-001",
        "name": "张三",
        "bank": "招商银行",
        "account_last4": "6621",
        "whitelisted": True,
        "added_days_ago": 420,
    },
    "BEN-002": {
        "beneficiary_id": "BEN-002",
        "customer_id": "CUST-001",
        "name": "李四",
        "bank": "中国工商银行",
        "account_last4": "2048",
        "whitelisted": True,
        "added_days_ago": 260,
    },
    "BEN-003": {
        "beneficiary_id": "BEN-003",
        "customer_id": "CUST-001",
        "name": "王五",
        "bank": "某城商行",
        "account_last4": "9911",
        "whitelisted": False,
        "added_days_ago": 2,
    },
}


# 策略参数放在独立配置文件中，便于版本化、审查和计算配置哈希。
_POLICY_CONFIG_PATH = Path(__file__).with_name("policy_config.json")
_POLICY_CONFIG = json.loads(
    _POLICY_CONFIG_PATH.read_text(encoding="utf-8")
)
_MONEY_POLICY_KEYS = {
    "confirm_threshold_cny",
    "large_amount_reminder_cny",
    "single_transfer_limit_cny",
    "daily_transfer_limit_cny",
    "transfer_fee_cny",
}
POLICY = {
    key: (D(value) if key in _MONEY_POLICY_KEYS else value)
    for key, value in _POLICY_CONFIG.items()
}


LOANS = {
    "CUST-001": [
        {
            "customer_id": "CUST-001",
            "loan_id": "LN-2023-0918",
            "type": "个人住房贷款",
            "principal": D("800000.00"),
            "outstanding": D("612340.55"),
            "annual_rate": "3.85%",
            "monthly_payment": D("3872.40"),
            "next_due_date": _next_month_day(5),
            "status": "normal",
        }
    ]
}


def _build_transactions() -> list[dict[str, Any]]:
    rng = random.Random(20261017)
    merchants: dict[str, list[tuple[str, float, float]]] = {
        "餐饮": [
            ("星巴克", 28, 68),
            ("海底捞", 180, 420),
            ("美团外卖", 25, 90),
            ("瑞幸咖啡", 15, 38),
            ("弄堂小馆", 30, 120),
        ],
        "交通": [
            ("滴滴出行", 18, 85),
            ("上海地铁", 3, 8),
            ("中国石化", 260, 520),
        ],
        "购物": [
            ("淘宝", 60, 800),
            ("京东", 100, 1200),
            ("盒马鲜生", 80, 350),
            ("优衣库", 199, 699),
        ],
        "娱乐": [
            ("猫眼电影", 45, 120),
            ("网易云音乐", 15, 15),
            ("健身月卡", 299, 299),
        ],
    }

    rows: list[dict[str, Any]] = []
    serial = 0

    def add(
        account_id: str,
        day: date,
        merchant: str,
        category: str,
        direction: str,
        amount: Any,
        channel: str,
    ) -> None:
        nonlocal serial
        serial += 1
        rows.append(
            {
                "tx_id": f"TX-{serial:05d}",
                "account_id": account_id,
                "date": day.isoformat(),
                "merchant": merchant,
                "category": category,
                "direction": direction,
                "amount": D(amount),
                "channel": channel,
            }
        )

    for account_id in ("ACC-4821", "ACC-9077"):
        for days_ago in range(90, -1, -1):
            day = TODAY - timedelta(days=days_ago)

            if account_id == "ACC-9077" and day.day == 10:
                add(
                    account_id,
                    day,
                    "工资入账",
                    "收入",
                    "credit",
                    23800 + rng.randint(-300, 300),
                    "代发",
                )

            if account_id == "ACC-4821" and day.day == 5:
                add(account_id, day, "房贷还款", "居住", "debit", "3872.40", "自动扣款")

            count = rng.choices([0, 1, 2], weights=[0.30, 0.50, 0.20], k=1)[0]
            for _ in range(count):
                category = rng.choices(
                    ["餐饮", "交通", "购物", "娱乐"],
                    weights=[0.40, 0.25, 0.25, 0.10],
                    k=1,
                )[0]
                merchant, low, high = rng.choice(merchants[category])
                add(
                    account_id,
                    day,
                    merchant,
                    category,
                    "debit",
                    rng.uniform(low, high),
                    rng.choice(["扫码", "线上", "POS"]),
                )

    # 一笔他人转入，方便展示收入类交易
    add(
        "ACC-4821",
        TODAY - timedelta(days=12),
        "转账-李四",
        "转账",
        "credit",
        "1200.00",
        "手机银行",
    )

    rows.sort(key=lambda row: (row["date"], row["tx_id"]), reverse=True)
    return rows


TRANSACTIONS = _build_transactions()


class MockBank:
    """内存核心系统。进程重启后所有变动都会丢失。"""

    def __init__(self, audit_redactor=None) -> None:
        self.audit_redactor = audit_redactor
        self.customers = deepcopy(CUSTOMERS)
        self.accounts = deepcopy(ACCOUNTS)
        self.cards = deepcopy(CARDS)
        self.beneficiaries = deepcopy(BENEFICIARIES)
        self.transactions = deepcopy(TRANSACTIONS)
        self.loans = deepcopy(LOANS)
        self.idempotency: dict[str, dict[str, Any]] = {}
        self.daily_transfers: dict[tuple[str, str], Decimal] = {}
        self.audit_log: list[dict[str, Any]] = []

    # ---------- 查询辅助 ----------

    def find_account(self, customer_id: str, ref: str | None) -> dict[str, Any]:
        ref = (ref or "").strip()
        owned = {
            account_id: account
            for account_id, account in self.accounts.items()
            if account["customer_id"] == customer_id
        }
        aliases = {
            "储蓄卡": "ACC-4821",
            "借记卡": "ACC-4821",
            "工资卡": "ACC-9077",
            "信用卡": "ACC-3312",
        }

        if ref in owned:
            return owned[ref]
        if ref in aliases and aliases[ref] in owned:
            return owned[aliases[ref]]
        if ref.isdigit():
            if len(ref) == 4:
                for account in owned.values():
                    if account["last4"] == ref:
                        return account
            for account in owned.values():
                if account["account_id"].endswith(ref):
                    return account
        if ref:
            for account in owned.values():
                if ref in account["type"] or ref == account["last4"]:
                    return account

        raise ToolError(
            "ACCOUNT_NOT_FOUND",
            "未找到该账户，或账户不属于当前登录客户。",
        )

    def find_card(self, customer_id: str, ref: str | None) -> dict[str, Any]:
        ref = (ref or "").strip()
        owned = {
            card_id: card
            for card_id, card in self.cards.items()
            if card["customer_id"] == customer_id
        }
        aliases = {
            "信用卡": "CARD-3312",
            "借记卡": "CARD-4821",
            "储蓄卡": "CARD-4821",
        }

        if ref in owned:
            return owned[ref]
        if ref in aliases and aliases[ref] in owned:
            return owned[aliases[ref]]
        if ref.isdigit():
            for card in owned.values():
                if card["last4"] == ref:
                    return card
        if ref:
            for card in owned.values():
                if ref in card["type"]:
                    return card

        raise ToolError(
            "CARD_NOT_FOUND",
            "未找到该卡片，或卡片不属于当前登录客户。",
        )

    def find_beneficiary(self, customer_id: str, name: str) -> dict[str, Any]:
        for beneficiary in self.beneficiaries.values():
            if (
                beneficiary["customer_id"] == customer_id
                and beneficiary["name"] == name.strip()
            ):
                return beneficiary
        raise ToolError(
            "BENEFICIARY_NOT_FOUND",
            f"未找到收款人「{name}」，请先在收款人名册中添加。",
        )

    # ---------- 限额与审计 ----------

    def daily_transfer_total(
        self, customer_id: str, day: date | None = None
    ) -> Decimal:
        key = (customer_id, (day or TODAY).isoformat())
        return self.daily_transfers.get(key, D("0.00"))

    def add_daily_transfer(self, customer_id: str, amount: Decimal) -> None:
        key = (customer_id, TODAY.isoformat())
        self.daily_transfers[key] = self.daily_transfers.get(key, D("0.00")) + amount

    def record_audit(self, entry: dict[str, Any]) -> None:
        record = {**entry, "at": entry.get("at") or utc_now()}
        if self.audit_redactor is not None:
            record = self.audit_redactor(record)
        self.audit_log.append(record)

    def account_balance_snapshot(self, account_id: str) -> str | None:
        account = self.accounts.get(account_id)
        if not account:
            return None
        if account["kind"] == "credit":
            return str(account["outstanding"])
        return str(account["balance"])
