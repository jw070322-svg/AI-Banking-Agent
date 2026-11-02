"""analysis.liquidity —— 跨场景联动：锁定预算后还能动用多少资金。

场景来源（比赛大纲第 6 项）：
"检测我爱人生日，当月锁定 1000 元活期，生日前 2 天订购鲜花、蛋糕。"

环境生成 Agent 的 F 场景已经提供：
- `budget.locked_amount_minor`：生日当月锁定的活动预算；
- `activity_calendar`：鲜花/蛋糕/晚餐等计划支出；
- `credit_card_bill`、`subscriptions`：其他已知扣款。

本模块在现金流投影的基础上回答：
1. 锁定之后，现在最多还能花多少（不考虑未来工资）？
2. 把未来 N 天的工资也算进来，最低点还能留多少缓冲？
3. 锁定的钱会不会被挤占？挤占多少？
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from .cashflow import project_cashflow
from .data import parse_date


def _planned_activity_total(projection: Dict[str, Any]) -> int:
    return -sum(
        event["amount_minor"] for event in projection["events"]
        if event["event_type"] == "planned_activity" and event["amount_minor"] < 0
    )


def _pre_income_lowest(projection: Dict[str, Any]) -> int:
    """第一笔未来收入到账前的最低余额（这才是"现在真正能动"的口径）。"""
    balance = projection["starting_balance_minor"]
    lowest = balance
    for event in projection["events"]:
        if event["event_type"] == "income":
            return lowest
        balance += event["amount_minor"]
        lowest = min(lowest, balance)
    return min(lowest, projection["lowest_balance_minor"])


def available_liquidity(
    data: Dict[str, Any],
    days: int = 30,
    today: Optional[date] = None,
    projection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """计算锁定预算后的可用流动性。

    - `reserved_remaining_minor`：锁定金额减去已计划的生日活动支出，
      剩下的钱仍然要留着，不能算作可动用资金；
    - `safe_to_spend_now_minor`：不考虑未来工资时，现在可以自由动用的金额；
    - `safe_to_spend_horizon_minor`：把未来 N 天工资也算进来后的安全上限；
    - `locked_amount_at_risk_minor`：未来最低余额低于预留金额的部分，
      大于 0 说明锁定预算会被日常支出挤占。
    """
    if projection is None:
        projection = project_cashflow(data, days=days, today=today)

    budget = data.get("budget") if isinstance(data.get("budget"), dict) else {}
    locked_amount = budget.get("locked_amount_minor")
    if not isinstance(locked_amount, int) or isinstance(locked_amount, bool) or locked_amount < 0:
        locked_amount = 0

    planned_activity = _planned_activity_total(projection)
    reserved_remaining = max(0, locked_amount - planned_activity)

    lowest = projection["lowest_balance_minor"]
    buffer_after_reserve = lowest - reserved_remaining
    locked_at_risk = max(0, -buffer_after_reserve)

    pre_income_lowest = _pre_income_lowest(projection)
    safe_now = max(0, pre_income_lowest - reserved_remaining)
    safe_horizon = max(0, buffer_after_reserve)

    warnings: List[str] = list(projection["warnings"])
    if locked_at_risk > 0:
        warnings.append(
            f"锁定预算预计被占用 {locked_at_risk / 100:.2f} 元，"
            f"最低余额 {lowest / 100:.2f} 元低于预留 {reserved_remaining / 100:.2f} 元"
        )

    lock_month = budget.get("lock_month")
    lock_active = True
    if lock_month:
        # 锁定月份已经结束（例如查看旧场景）时，预留金自动释放
        try:
            lock_end = parse_date(f"{lock_month}-01")
        except (TypeError, ValueError):
            lock_end = None
        if lock_end is not None:
            reference = parse_date(projection["as_of"])
            if reference is not None:
                lock_active = (reference.year, reference.month) <= (
                    lock_end.year, lock_end.month
                )
    if not lock_active:
        reserved_remaining = 0
        locked_at_risk = 0
        buffer_after_reserve = lowest
        safe_now = pre_income_lowest
        safe_horizon = max(0, lowest)

    return {
        "as_of": projection["as_of"],
        "horizon_days": days,
        "currency": "CNY",
        "current_balance_minor": projection["starting_balance_minor"],
        "locked_amount_minor": locked_amount,
        "lock_active": lock_active,
        "lock_month": lock_month,
        "planned_activity_minor": planned_activity,
        "reserved_remaining_minor": reserved_remaining,
        "upcoming_obligations_minor": projection["scheduled_outflow_minor"],
        "expected_income_minor": projection["expected_income_minor"],
        "minimum_balance_minor": lowest,
        "minimum_balance_date": projection["lowest_balance_date"],
        "buffer_after_reserve_minor": buffer_after_reserve,
        "safe_to_spend_now_minor": safe_now,
        "safe_to_spend_horizon_minor": safe_horizon,
        "locked_amount_at_risk_minor": locked_at_risk,
        "shortfall_days": projection["shortfall_days"],
        "warnings": warnings,
        "projection": projection,
    }
