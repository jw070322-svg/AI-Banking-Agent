"""analysis.aggregate —— 消费分类统计与月度/年度账单报告。

所有金额都是 CNY 整数分（minor units），可以直接交给接口或前端渲染。

典型用法：
>>> report = monthly_report(data, "2026-10")
>>> report["spending_minor"]
123400
>>> report["categories"][0]["category"]
'购物'
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .data import (
    available_months,
    consumption_entries,
    deposit_transactions,
    income_entries,
    month_of,
    transfer_out_minor,
)


def _share_bp(amount_minor: int, total_minor: int) -> int:
    """占比（万分比，整数）。"""
    if total_minor <= 0:
        return 0
    return int(round(amount_minor * 10000 / total_minor))


def _category_table(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按类别汇总，返回按金额从大到小排列的列表。"""
    totals: Dict[str, int] = {}
    counts: Dict[str, int] = {}
    for entry in entries:
        category = entry["category"]
        totals[category] = totals.get(category, 0) + entry["amount_minor"]
        counts[category] = counts.get(category, 0) + 1

    grand_total = sum(amount for amount in totals.values() if amount > 0)
    table = [
        {
            "category": category,
            "spending_minor": amount,
            "transaction_count": counts[category],
            "share_bp": _share_bp(amount, grand_total),
        }
        for category, amount in totals.items()
        if amount != 0
    ]
    table.sort(key=lambda row: (-row["spending_minor"], row["category"]))
    return table


def _merchant_table(entries: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    """商户消费排行（只统计正消费）。"""
    totals: Dict[str, int] = {}
    for entry in entries:
        if entry["amount_minor"] <= 0 or not entry["merchant"]:
            continue
        totals[entry["merchant"]] = totals.get(entry["merchant"], 0) + entry["amount_minor"]
    rows = [
        {"merchant": merchant, "spending_minor": amount}
        for merchant, amount in totals.items()
    ]
    rows.sort(key=lambda row: (-row["spending_minor"], row["merchant"]))
    return rows[:limit]


def _month_summary(data: Dict[str, Any], month: str) -> Dict[str, Any]:
    entries = consumption_entries(data, month=month)
    income = sum(entry["amount_minor"] for entry in income_entries(data, month=month))
    spending = sum(entry["amount_minor"] for entry in entries)
    transfers = transfer_out_minor(data, month=month)
    return {
        "month": month,
        "currency": "CNY",
        "income_minor": income,
        "spending_minor": spending,
        "transfer_out_minor": transfers,
        "net_minor": income - spending - transfers,
        "categories": _category_table(entries),
        "transaction_count": _transaction_count(data, month),
    }


def _transaction_count(data: Dict[str, Any], month: Optional[str] = None) -> int:
    deposit_count = sum(
        1 for transaction in deposit_transactions(data)
        if month is None or month_of(transaction.get("date")) == month
    )
    bill = data.get("credit_card_bill") or {}
    credit_count = sum(
        1 for item in bill.get("items", [])
        if isinstance(item, dict)
        and (month is None or month_of(item.get("date")) == month)
    )
    return deposit_count + credit_count


def _credit_card_block(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    bill = data.get("credit_card_bill")
    if not isinstance(bill, dict):
        return None
    return {
        "card_id": bill.get("card_id"),
        "statement_date": bill.get("statement_date"),
        "due_date": bill.get("due_date"),
        "status": bill.get("status"),
        "total_amount_minor": bill.get("total_amount_minor", 0),
        "paid_amount_minor": bill.get("paid_amount_minor", 0),
        "outstanding_amount_minor": bill.get("outstanding_amount_minor", 0),
    }


def _active_subscriptions_minor(data: Dict[str, Any]) -> int:
    total = 0
    for subscription in data.get("subscriptions", []) or []:
        if subscription.get("status") != "active":
            continue
        amount = subscription.get("amount_minor")
        if isinstance(amount, int) and not isinstance(amount, bool):
            total += amount
    return total


def monthly_report(data: Dict[str, Any], month: str) -> Dict[str, Any]:
    """生成某个月的账单报告。"""
    summary = _month_summary(data, month)
    entries = consumption_entries(data, month=month)
    summary["top_merchants"] = _merchant_table(entries)
    summary["credit_card"] = _credit_card_block(data)
    summary["active_subscriptions_minor"] = _active_subscriptions_minor(data)
    summary["available_balance_minor"] = sum(
        account.get("balance_minor", 0)
        for account in data.get("accounts", [])
        if isinstance(account.get("balance_minor"), int)
    )
    return summary


def annual_report(data: Dict[str, Any], year: int) -> Dict[str, Any]:
    """生成某一年的年度账单报告（含逐月汇总）。"""
    prefix = f"{year:04d}-"
    months = [month for month in available_months(data) if month.startswith(prefix)]
    monthly = [_month_summary(data, month) for month in months]

    entries = [
        entry for entry in consumption_entries(data)
        if entry["month"].startswith(prefix)
    ]
    income = sum(entry["amount_minor"] for entry in income_entries(data)
                 if entry["month"].startswith(prefix))
    spending = sum(entry["amount_minor"] for entry in entries)
    transfers = sum(summary["transfer_out_minor"] for summary in monthly)

    return {
        "year": year,
        "currency": "CNY",
        "income_minor": income,
        "spending_minor": spending,
        "transfer_out_minor": transfers,
        "net_minor": income - spending - transfers,
        "transaction_count": sum(summary["transaction_count"] for summary in monthly),
        "categories": _category_table(entries),
        "top_merchants": _merchant_table(entries),
        "months": [
            {
                "month": summary["month"],
                "income_minor": summary["income_minor"],
                "spending_minor": summary["spending_minor"],
                "net_minor": summary["net_minor"],
            }
            for summary in monthly
        ],
    }


def overall_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    """不限定年份的整体汇总（方便快速预览）。"""
    entries = consumption_entries(data)
    income = sum(entry["amount_minor"] for entry in income_entries(data))
    spending = sum(entry["amount_minor"] for entry in entries)
    transfers = transfer_out_minor(data)
    monthly = [_month_summary(data, month) for month in available_months(data)]
    return {
        "currency": "CNY",
        "income_minor": income,
        "spending_minor": spending,
        "transfer_out_minor": transfers,
        "net_minor": income - spending - transfers,
        "transaction_count": _transaction_count(data),
        "categories": _category_table(entries),
        "top_merchants": _merchant_table(entries),
        "months": [
            {
                "month": summary["month"],
                "income_minor": summary["income_minor"],
                "spending_minor": summary["spending_minor"],
                "net_minor": summary["net_minor"],
            }
            for summary in monthly
        ],
    }


def category_breakdown(
    data: Dict[str, Any],
    month: Optional[str] = None,
    year: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """按类别汇总消费，可按月或按年过滤。"""
    entries = consumption_entries(data, month=month)
    if year is not None:
        prefix = f"{year:04d}-"
        entries = [entry for entry in entries if entry["month"].startswith(prefix)]
    return _category_table(entries)
