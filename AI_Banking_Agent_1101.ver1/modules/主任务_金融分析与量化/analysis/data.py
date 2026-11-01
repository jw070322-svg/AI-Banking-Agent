"""analysis.data —— 把场景数据整理成分析用的统一视图。

统一约定（很重要）：
- 金额全部是 **CNY 整数分**；
- 消费 `amount_minor` 为正，退款为负；
- 只看已入账（booked）的交易；
- 信用卡消费来自 `credit_card_bill.items`，与借记卡消费合并统计；
- 转账（transfer_in/transfer_out）不是消费，单列出来。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional


def parse_date(value: Any) -> Optional[date]:
    """解析 YYYY-MM-DD；失败返回 None。"""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def month_of(value: Any) -> Optional[str]:
    """从日期字符串取 YYYY-MM。"""
    if isinstance(value, str) and len(value) >= 7:
        return value[:7]
    return None


def is_booked(transaction: Dict[str, Any]) -> bool:
    return transaction.get("status") == "booked"


def deposit_transactions(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """借记卡/活期账户的已入账流水。"""
    return [
        transaction for transaction in data.get("transactions", [])
        if isinstance(transaction, dict) and is_booked(transaction)
    ]


def credit_items(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """信用卡账单里的已入账消费明细。"""
    bill = data.get("credit_card_bill") or {}
    return [
        item for item in bill.get("items", [])
        if isinstance(item, dict) and is_booked(item)
    ]


def consumption_entries(
    data: Dict[str, Any],
    month: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """返回消费条目（借记卡 + 信用卡），支出为正、退款为负。

    每条包含：
    - transaction_id / date / month / merchant / category
    - amount_minor（带符号）
    - source：deposit / credit_card
    - time（如果有）
    """
    entries: List[Dict[str, Any]] = []

    for transaction in deposit_transactions(data):
        transaction_type = transaction.get("transaction_type")
        amount = transaction.get("amount_minor")
        if not isinstance(amount, int) or isinstance(amount, bool):
            continue
        if transaction_type == "expense":
            signed = amount
        elif transaction_type == "refund":
            signed = -amount
        else:
            continue
        entry = _entry(transaction, signed, "deposit")
        if entry is not None:
            entries.append(entry)

    for item in credit_items(data):
        transaction_type = item.get("transaction_type")
        amount = item.get("amount_minor")
        if not isinstance(amount, int) or isinstance(amount, bool):
            continue
        if transaction_type == "expense":
            signed = amount
        elif transaction_type == "refund":
            signed = -amount
        else:
            continue
        entry = _entry(item, signed, "credit_card")
        if entry is not None:
            entries.append(entry)

    if month is not None:
        entries = [entry for entry in entries if entry["month"] == month]
    entries.sort(key=lambda entry: (entry["date"], entry["transaction_id"]))
    return entries


def _entry(raw: Dict[str, Any], signed_amount: int, source: str) -> Optional[Dict[str, Any]]:
    entry_date = raw.get("date")
    if parse_date(entry_date) is None:
        return None
    return {
        "transaction_id": raw.get("transaction_id"),
        "date": entry_date,
        "month": entry_date[:7],
        "merchant": raw.get("merchant") or "",
        "category": raw.get("category") or "未分类",
        "amount_minor": signed_amount,
        "source": source,
        "time": raw.get("time"),
    }


def income_entries(
    data: Dict[str, Any],
    month: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """已入账收入（工资、转入以外只算 income 类型）。"""
    entries: List[Dict[str, Any]] = []
    for transaction in deposit_transactions(data):
        if transaction.get("transaction_type") != "income":
            continue
        amount = transaction.get("amount_minor")
        if not isinstance(amount, int) or isinstance(amount, bool):
            continue
        entry_date = transaction.get("date")
        if parse_date(entry_date) is None:
            continue
        if month is not None and entry_date[:7] != month:
            continue
        entries.append({
            "transaction_id": transaction.get("transaction_id"),
            "date": entry_date,
            "month": entry_date[:7],
            "merchant": transaction.get("merchant") or "",
            "category": transaction.get("category") or "收入",
            "amount_minor": amount,
        })
    entries.sort(key=lambda entry: entry["date"])
    return entries


def transfer_out_minor(data: Dict[str, Any], month: Optional[str] = None) -> int:
    """转出金额合计（不是消费，单独统计）。"""
    total = 0
    for transaction in deposit_transactions(data):
        if transaction.get("transaction_type") != "transfer_out":
            continue
        entry_date = transaction.get("date")
        if month is not None and (not isinstance(entry_date, str) or entry_date[:7] != month):
            continue
        amount = transaction.get("amount_minor")
        if isinstance(amount, int) and not isinstance(amount, bool):
            total += amount
    return total


def available_months(data: Dict[str, Any]) -> List[str]:
    """数据里出现过的所有月份，升序。"""
    months = set()
    for transaction in data.get("transactions", []):
        if isinstance(transaction, dict):
            month = month_of(transaction.get("date"))
            if month:
                months.add(month)
    for item in credit_items(data):
        month = month_of(item.get("date"))
        if month:
            months.add(month)
    return sorted(months)


def reference_date(data: Dict[str, Any], today: Optional[date] = None) -> date:
    """分析基准日：优先使用调用方传入的 today，否则用场景 created_at 的日期。"""
    if today is not None:
        return today
    created = data.get("created_at")
    parsed = parse_date(created[:10]) if isinstance(created, str) and len(created) >= 10 else None
    return parsed or date.today()
