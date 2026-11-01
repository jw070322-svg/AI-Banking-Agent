"""analysis.cashflow —— 订阅负担与未来现金流投影。

回答两个用户真正关心的问题：

1. "我的订阅一个月/一年要花多少钱？占收入多少？" → `subscription_burden()`
2. "未来 30/90 天，工资、信用卡还款、订阅续费排在一起，我会不会不够钱？"
   → `project_cashflow()`

所有金额仍然是 CNY 整数分。投影是**确定性推演**，不是收益预测：
- 期初余额取账户 `balance_minor` 之和；
- 收入只按历史工资日推算；
- 支出只包含已知的信用卡未还账单、订阅续费、生日活动日历里的计划支出；
- 同一天先扣支出再进收入，故意取保守口径。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .data import (
    income_entries,
    parse_date,
    reference_date,
)

# 订阅负担分级（原型约定，不是现实银行的监管标准）
BURDEN_LOW = 0.03      # 3% 以下：低
BURDEN_MEDIUM = 0.08   # 3%~8%：中；8% 以上：高


def _days_in_month(year: int, month: int) -> int:
    next_month = date(year, month, 28) + timedelta(days=4)
    return (next_month.replace(day=1) - timedelta(days=1)).day


def _shift_month(value: date, delta: int) -> date:
    index = value.year * 12 + (value.month - 1) + delta
    year, month_index = divmod(index, 12)
    month = month_index + 1
    return date(year, month, min(value.day, _days_in_month(year, month)))


def _next_day_after(today: date, day: int) -> date:
    """严格晚于 today 的下一个"某月 day 号"。"""
    day = min(max(1, day), 28)
    candidate = date(today.year, today.month, day)
    if candidate <= today:
        following = _shift_month(date(today.year, today.month, 1), 1)
        candidate = date(
            following.year, following.month,
            min(day, _days_in_month(following.year, following.month)),
        )
    return candidate


def _monthly_equivalent(amount_minor: int, cycle: Optional[str]) -> int:
    """把季度/年度订阅折算成每月金额（四舍五入到分）。"""
    if cycle == "quarterly":
        return int(round(amount_minor / 3))
    if cycle == "yearly":
        return int(round(amount_minor / 12))
    return amount_minor


def _cycle_months(cycle: Optional[str]) -> int:
    if cycle == "quarterly":
        return 3
    if cycle == "yearly":
        return 12
    return 1


def _latest_salary(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    salaries = [
        entry for entry in income_entries(data)
        if entry["category"] == "工资" or "工资" in str(entry["category"])
    ]
    if not salaries:
        return None
    return max(salaries, key=lambda entry: (entry["date"], entry["transaction_id"] or ""))


def subscription_burden(data: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    """订阅负担：月均支出、占工资比例、即将扣费明细。"""
    base_date = reference_date(data, today)
    salary = _latest_salary(data)
    assumptions=data.get('cashflow_assumptions') or {}
    monthly_income = assumptions.get('monthly_income_minor',salary["amount_minor"] if salary else 0)

    items: List[Dict[str, Any]] = []
    monthly_total = 0
    upcoming_7 = 0
    upcoming_30 = 0

    for subscription in data.get("subscriptions", []) or []:
        if subscription.get("status") != "active":
            continue
        amount = subscription.get("amount_minor")
        if not isinstance(amount, int) or isinstance(amount, bool):
            continue
        cycle = subscription.get("cycle")
        monthly = _monthly_equivalent(amount, cycle)
        monthly_total += monthly

        next_charge = parse_date(subscription.get("next_charge_date"))
        days_until = (next_charge - base_date).days if next_charge else None
        if days_until is not None and days_until <= 7:
            upcoming_7 += amount
        if days_until is not None and days_until <= 30:
            upcoming_30 += amount

        items.append({
            "subscription_id": subscription.get("subscription_id"),
            "merchant": subscription.get("merchant"),
            "amount_minor": amount,
            "cycle": cycle,
            "monthly_equivalent_minor": monthly,
            "next_charge_date": subscription.get("next_charge_date"),
            "days_until_charge": days_until,
        })

    items.sort(key=lambda item: (-item["monthly_equivalent_minor"], item["merchant"] or ""))

    ratio = (monthly_total / monthly_income) if monthly_income > 0 else None
    if ratio is None:
        level = None
    elif ratio < BURDEN_LOW:
        level = "low"
    elif ratio < BURDEN_MEDIUM:
        level = "medium"
    else:
        level = "high"

    return {
        "as_of": base_date.isoformat(),
        "currency": "CNY",
        "active_count": len(items),
        "monthly_total_minor": monthly_total,
        "annual_total_minor": monthly_total * 12,
        "monthly_income_minor": monthly_income,
        "income_source": "configured_future_income" if 'monthly_income_minor' in assumptions else "latest_salary" if salary else None,
        "burden_ratio": round(ratio, 4) if ratio is not None else None,
        "burden_level": level,
        "upcoming_7_days_minor": upcoming_7,
        "upcoming_30_days_minor": upcoming_30,
        "items": items,
        "thresholds": {"low": BURDEN_LOW, "medium": BURDEN_MEDIUM},
    }


def _salary_events(
    data: Dict[str, Any],
    today: date,
    horizon_end: date,
) -> List[Dict[str, Any]]:
    salary = _latest_salary(data)
    assumptions=data.get('cashflow_assumptions') or {}
    if salary is None and 'monthly_income_minor' not in assumptions:
        return []

    salary_day = assumptions.get('salary_day',int(salary["date"][8:10]) if salary else 15)
    amount = assumptions.get('monthly_income_minor',salary["amount_minor"] if salary else 0)
    if amount<=0: return []
    events: List[Dict[str, Any]] = []

    event_date = _next_day_after(today, salary_day)
    while event_date <= horizon_end:
        events.append({
            "date": event_date.isoformat(),
            "event_type": "income",
            "title": "工资到账",
            "amount_minor": amount,
        })
        event_date = _next_day_after(event_date, salary_day)
    return events


def _credit_bill_event(
    data: Dict[str, Any],
    today: date,
    horizon_end: date,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    bill = data.get("credit_card_bill")
    if not isinstance(bill, dict):
        return [], []
    outstanding = bill.get("outstanding_amount_minor")
    if not isinstance(outstanding, int) or isinstance(outstanding, bool) or outstanding <= 0:
        return [], []

    warnings: List[str] = []
    due = parse_date(bill.get("due_date"))
    if due is None:
        return [], warnings
    if due < today:
        warnings.append(f"信用卡账单已于 {due.isoformat()} 逾期，按今天还款估算")
        event_date = today
    elif due <= horizon_end:
        event_date = due
    else:
        return [], warnings

    return [{
        "date": event_date.isoformat(),
        "event_type": "credit_card",
        "title": "信用卡还款",
        "amount_minor": -outstanding,
        "card_id": bill.get("card_id"),
    }], warnings


def _subscription_events(
    data: Dict[str, Any],
    today: date,
    horizon_end: date,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for subscription in data.get("subscriptions", []) or []:
        if subscription.get("status") != "active":
            continue
        amount = subscription.get("amount_minor")
        if not isinstance(amount, int) or isinstance(amount, bool):
            continue
        charge = parse_date(subscription.get("next_charge_date"))
        if charge is None:
            continue
        months = _cycle_months(subscription.get("cycle"))
        while charge < today:
            charge = _shift_month(charge, months)
        while charge <= horizon_end:
            events.append({
                "date": charge.isoformat(),
                "event_type": "subscription",
                "title": f"{subscription.get('merchant', '订阅')}续费",
                "amount_minor": -amount,
                "subscription_id": subscription.get("subscription_id"),
            })
            charge = _shift_month(charge, months)
    return events


def _planned_activity_events(
    data: Dict[str, Any],
    today: date,
    horizon_end: date,
) -> List[Dict[str, Any]]:
    """生日活动日历里的计划支出（鲜花、蛋糕、晚餐等）。"""
    events: List[Dict[str, Any]] = []
    for entry in data.get("activity_calendar", []) or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") in {"done", "cancelled"}:
            continue
        budget = entry.get("budget_minor")
        event_date = parse_date(entry.get("date"))
        if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
            continue
        if event_date is None or event_date < today or event_date > horizon_end:
            continue
        events.append({
            "date": event_date.isoformat(),
            "event_type": "planned_activity",
            "title": entry.get("title") or entry.get("category") or "生日活动",
            "amount_minor": -budget,
        })
    return events


def project_cashflow(
    data: Dict[str, Any],
    days: int = 30,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """未来 N 天的可用余额投影。

    `days` 取值 1~366。返回逐笔事件、最低余额、是否出现缺口。
    """
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 366:
        raise ValueError("days 必须是 1~366 的整数")

    base_date = reference_date(data, today)
    horizon_end = base_date + timedelta(days=days)

    starting_balance = sum(
        account.get("balance_minor", 0)
        for account in data.get("accounts", [])
        if isinstance(account.get("balance_minor"), int)
        and not isinstance(account.get("balance_minor"), bool)
    )

    events: List[Dict[str, Any]] = []
    events.extend(_salary_events(data, base_date, horizon_end))
    bill_events, warnings = _credit_bill_event(data, base_date, horizon_end)
    events.extend(bill_events)
    assumptions=data.get('cashflow_assumptions') or {}
    if 'monthly_expense_minor' in assumptions:
        # Session budgets already include subscriptions; do not charge them twice.
        expense_date=_next_day_after(base_date,assumptions.get('expense_day',5))
        while expense_date<=horizon_end:
            if assumptions['monthly_expense_minor']>0:
                events.append({'date':expense_date.isoformat(),'event_type':'configured_expense','title':'已配置月度支出（含订阅）','amount_minor':-assumptions['monthly_expense_minor']})
            expense_date=_next_day_after(expense_date,assumptions.get('expense_day',5))
    else: events.extend(_subscription_events(data, base_date, horizon_end))
    events.extend(_planned_activity_events(data, base_date, horizon_end))

    # 同一天先扣支出再进收入，保证最低余额口径偏保守
    events.sort(key=lambda event: (
        event["date"], 0 if event["amount_minor"] < 0 else 1, event["event_type"]
    ))

    balance = starting_balance
    lowest = starting_balance
    lowest_date = base_date.isoformat()
    shortfall_days: List[str] = []

    for event in events:
        balance += event["amount_minor"]
        event["balance_after_minor"] = balance
        if balance < lowest:
            lowest = balance
            lowest_date = event["date"]
        if balance < 0 and event["date"] not in shortfall_days:
            shortfall_days.append(event["date"])

    income_total = sum(event["amount_minor"] for event in events if event["amount_minor"] > 0)
    outflow_total = -sum(event["amount_minor"] for event in events if event["amount_minor"] < 0)

    if lowest < 0:
        warnings.append(
            f"预计 {lowest_date} 余额为负，最大缺口 {-lowest / 100:.2f} 元"
        )

    return {
        "as_of": base_date.isoformat(),
        "horizon_end": horizon_end.isoformat(),
        "horizon_days": days,
        "currency": "CNY",
        "starting_balance_minor": starting_balance,
        "expected_income_minor": income_total,
        "scheduled_outflow_minor": outflow_total,
        "ending_balance_minor": balance,
        "lowest_balance_minor": lowest,
        "lowest_balance_date": lowest_date,
        "shortfall_days": shortfall_days,
        "events": events,
        "warnings": warnings,
    }
