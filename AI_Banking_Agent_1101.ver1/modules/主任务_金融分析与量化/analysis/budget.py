"""analysis.budget —— 每月可安全增加的储蓄/投资额。

回答比赛「理财操作」和「跨场景联动」里的一个问题：
"按现在的收入和支出，我每个月最多能拿出多少钱存起来或投资，而不会让
未来现金流断档？"

计算分三步，全部复用已有模块，不重复实现：

1. 月度结余 = 当月收入 - 消费 - 转出（来自 `monthly_report`）；
2. 现金流最低余额 = `project_cashflow` 推演未来 N 天的结果；
3. 扣掉生日锁定预留和应急缓冲后，折算成每 30 天的可动用额度。

两条约束（原型策略，不是监管规则）：
- 储蓄：活期账户保留 1 个月支出作为最低缓冲；
- 投资：锁定资金前保留 3 个月支出作为应急金，避免急用钱时被动赎回。

所有金额是 CNY 整数分；结果只读，不写账本，也不是收益预测。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from .aggregate import monthly_report
from .cashflow import project_cashflow, subscription_burden
from .data import available_months
from .liquidity import available_liquidity

# 原型策略：储蓄保留 1 个月支出，投资保留 3 个月支出，可按业务需要调整
SAVINGS_RESERVE_MONTHS = 1
INVESTMENT_RESERVE_MONTHS = 3


def _per_month(amount_minor: int, days: int) -> int:
    """把整个投影期内的额度折算成每 30 天额度（整数分，向下取整）。"""
    return amount_minor * 30 // days


def _binding_constraint(
    safe_minor: int,
    surplus_minor: int,
    capacity_minor: int,
    *,
    income_minor: int,
    has_shortfall: bool,
) -> str:
    """指出是哪条约束卡住了建议金额。"""
    if income_minor <= 0:
        return "insufficient_income"
    if has_shortfall:
        return "cashflow_shortfall"
    if safe_minor <= 0:
        return "liquidity_reserve"
    if safe_minor == surplus_minor and safe_minor == capacity_minor:
        return "both"
    if safe_minor == surplus_minor:
        return "monthly_surplus"
    return "liquidity_reserve"


def _reserve_months(
    value: Optional[int], name: str, default: int
) -> int:
    """校验回测用的缓冲月数；None 时使用模块默认策略。"""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 24:
        raise ValueError(f"{name} 必须是 0~24 的整数")
    return value


def budget_advice(
    data: Dict[str, Any],
    days: int = 30,
    month: Optional[str] = None,
    today: Optional[date] = None,
    projection: Optional[Dict[str, Any]] = None,
    savings_reserve_months: Optional[int] = None,
    investment_reserve_months: Optional[int] = None,
) -> Dict[str, Any]:
    """计算每月可安全储蓄/投资的金额及其约束。

    `days` 是现金流投影期，1~366 天；建议金额统一折算为每 30 天。
    `month` 是月度结余的统计月份，默认取数据里最新月份。
    两个 `*_reserve_months` 只给参数化回测使用；默认仍是 1 个月 / 3 个月。
    """
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 366:
        raise ValueError("days 必须是 1~366 的整数")

    savings_months = _reserve_months(
        savings_reserve_months, "savings_reserve_months", SAVINGS_RESERVE_MONTHS
    )
    investment_months = _reserve_months(
        investment_reserve_months, "investment_reserve_months", INVESTMENT_RESERVE_MONTHS
    )

    months = available_months(data)
    basis_month = month or (months[-1] if months else None)
    report = monthly_report(data, basis_month) if basis_month else None

    # 工资可能在上个月发放（例如 C 场景：9 月工资 + 10 月支出）。
    # 收入取“统计月份收入”与“最近一笔工资”的较大值，避免跨月发薪被误判为无收入。
    report_income = report["income_minor"] if report else 0
    subscription = subscription_burden(data, today=today)
    salary_income = subscription["monthly_income_minor"]
    income = max(report_income, salary_income)
    if report_income >= salary_income and report_income > 0:
        income_source = "month_report"
    elif salary_income > 0:
        income_source = "latest_salary"
    else:
        income_source = None

    spending = report["spending_minor"] if report else 0
    transfers = report["transfer_out_minor"] if report else 0
    assumptions=data.get('cashflow_assumptions') or {}
    if 'monthly_income_minor' in assumptions and 'monthly_expense_minor' in assumptions:
        income=assumptions['monthly_income_minor'];spending=assumptions['monthly_expense_minor'];transfers=0
        income_source='configured_future_income'
    surplus = max(0, income - spending - transfers)

    if projection is None:
        projection = project_cashflow(data, days=days, today=today)
    liquidity = available_liquidity(
        data, days=days, today=today, projection=projection
    )

    # 已扣掉生日锁定预算后、未来最低点的缓冲
    buffer_after_reserve = liquidity["buffer_after_reserve_minor"]
    shortfall = bool(projection["shortfall_days"])

    # 退款大于消费的月份 spending 可能为负，缓冲不能跟着变成负数
    reserve_base = max(0, spending)
    savings_reserve = reserve_base * savings_months
    investment_reserve = reserve_base * investment_months
    savings_headroom = max(0, buffer_after_reserve - savings_reserve)
    investment_headroom = max(0, buffer_after_reserve - investment_reserve)
    savings_capacity = _per_month(savings_headroom, days)
    investment_capacity = _per_month(investment_headroom, days)

    safe_to_save = min(surplus, savings_capacity)
    safe_to_invest = min(surplus, investment_capacity)

    warnings: List[str] = list(projection["warnings"])
    if income <= 0:
        warnings.append("缺少收入数据，无法给出储蓄/投资建议")
    if spending <= 0:
        warnings.append("缺少支出数据，应急缓冲按 0 计算，建议先补全流水")
    elif income > 0 and spending * 10 < income:
        warnings.append("支出不足收入的 10%，支出样本可能不完整，应急缓冲可能偏低")
    if shortfall:
        warnings.append("未来现金流存在缺口，建议先补足缺口，再考虑新增储蓄或投资")
    if safe_to_save <= 0 and income > 0 and not shortfall:
        warnings.append("扣除未来义务和最低缓冲后没有可安全动用的结余")
    if safe_to_invest <= 0 < safe_to_save:
        warnings.append(
            "现有余额不足 3 个月支出，建议先补应急金；新增资金以活期储蓄为主"
        )
    if len(months) < 3:
        warnings.append("当前只有不足 3 个月流水，建议结合更长周期校准")

    if income <= 0:
        recommended_action = "insufficient_data"
    elif shortfall:
        recommended_action = "fix_cashflow"
    elif safe_to_invest > 0:
        recommended_action = "invest"
    elif safe_to_save > 0:
        recommended_action = "build_emergency_fund"
    else:
        recommended_action = "none"

    credit_bill = data.get("credit_card_bill")
    outstanding = (
        credit_bill.get("outstanding_amount_minor")
        if isinstance(credit_bill, dict)
        else None
    )
    if not isinstance(outstanding, int) or isinstance(outstanding, bool):
        outstanding = 0

    return {
        "as_of": projection["as_of"],
        "horizon_days": days,
        "horizon_months": round(days / 30, 2),
        "currency": "CNY",
        "basis_month": basis_month,
        "monthly_income_minor": income,
        "income_source": income_source,
        "monthly_spending_minor": spending,
        "monthly_transfer_out_minor": transfers,
        "monthly_surplus_minor": surplus,
        "starting_balance_minor": projection["starting_balance_minor"],
        "lowest_balance_minor": projection["lowest_balance_minor"],
        "lowest_balance_date": projection["lowest_balance_date"],
        "shortfall_days": projection["shortfall_days"],
        "locked_amount_minor": liquidity["locked_amount_minor"],
        "reserved_remaining_minor": liquidity["reserved_remaining_minor"],
        "buffer_after_reserve_minor": buffer_after_reserve,
        "policy": {
            "savings_reserve_months": savings_months,
            "investment_reserve_months": investment_months,
        },
        "savings": {
            "reserve_floor_minor": savings_reserve,
            "headroom_minor": savings_headroom,
            "monthly_capacity_minor": savings_capacity,
            "safe_monthly_minor": safe_to_save,
            "binding_constraint": _binding_constraint(
                safe_to_save, surplus, savings_capacity,
                income_minor=income, has_shortfall=shortfall,
            ),
        },
        "investment": {
            "reserve_floor_minor": investment_reserve,
            "headroom_minor": investment_headroom,
            "monthly_capacity_minor": investment_capacity,
            "safe_monthly_minor": safe_to_invest,
            "binding_constraint": _binding_constraint(
                safe_to_invest, surplus, investment_capacity,
                income_minor=income, has_shortfall=shortfall,
            ),
        },
        "recommended_action": recommended_action,
        "context": {
            "subscription_monthly_minor": subscription["monthly_total_minor"],
            "subscription_burden_ratio": subscription["burden_ratio"],
            "subscription_burden_level": subscription["burden_level"],
            "credit_card_outstanding_minor": outstanding,
            "months_of_history": len(months),
        },
        "warnings": warnings,
        "assumptions": [
            "月度结余 = 当月收入 - 消费 - 转出；转出按资金流出保守处理",
            "现金流投影只含已知工资、信用卡还款、订阅续费和生日活动，不含未知消费",
            f"储蓄保留 {savings_months} 个月支出；投资保留 {investment_months} 个月支出作为应急缓冲",
            "金额为整数分，是确定性推演，不是收益预测",
        ],
        "simulated": True,
        "ledger_modified": False,
    }
