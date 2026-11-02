"""Deterministic financial calculations.

No random numbers and no floating-point money arithmetic are used. Results are
planning illustrations, not bank pricing, credit decisions, investment advice,
or operational risk decisions.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from .utils import (
    clamp,
    money,
    money_text,
    percent_text,
    ratio_text,
    to_decimal,
)

ZERO = Decimal("0.00")
ONE = Decimal("1")
HUNDRED = Decimal("100")
ASSET_ASSUMPTIONS: dict[str, dict[str, str]] = {
    "cash": {
        "label": "现金/活期存款",
        "expected_annual_return_percent": "1.50",
        "annual_volatility_percent": "0.50",
    },
    "bonds": {
        "label": "债券",
        "expected_annual_return_percent": "3.20",
        "annual_volatility_percent": "5.00",
    },
    "domestic_equity": {
        "label": "境内股票",
        "expected_annual_return_percent": "7.00",
        "annual_volatility_percent": "18.00",
    },
    "global_equity": {
        "label": "全球股票",
        "expected_annual_return_percent": "8.00",
        "annual_volatility_percent": "20.00",
    },
    "gold": {
        "label": "黄金",
        "expected_annual_return_percent": "4.00",
        "annual_volatility_percent": "12.00",
    },
    "crypto": {
        "label": "加密资产（高波动）",
        "expected_annual_return_percent": "10.00",
        "annual_volatility_percent": "60.00",
    },
}
ASSET_CLASSES = tuple(ASSET_ASSUMPTIONS)


def cashflow_summary(
    transactions: Iterable[dict[str, Any]],
    *,
    include_transfers: bool = False,
) -> dict[str, Any]:
    """Aggregate income/expenses and monthly/category splits.

    The caller supplies an already date-scoped transaction list. Internal
    transfers are excluded by default because counting both legs would inflate
    income and spending. A 30-day month is used for averaging; that assumption
    is returned in the payload.
    """
    rows = list(transactions)
    if not include_transfers:
        rows = [row for row in rows if row.get("category") != "转账"]

    total_income = ZERO
    total_expenses = ZERO
    category_totals: dict[str, dict[str, Any]] = {}
    monthly: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"income": ZERO, "expenses": ZERO}
    )

    for row in rows:
        amount = money(row["amount"])
        month = str(row["date"])[:7]
        if row["direction"] == "credit":
            total_income += amount
            monthly[month]["income"] += amount
        else:
            total_expenses += amount
            monthly[month]["expenses"] += amount
            category = str(row.get("category") or "未分类")
            bucket = category_totals.setdefault(
                category, {"count": 0, "amount": ZERO}
            )
            bucket["count"] += 1
            bucket["amount"] += amount

    net = total_income - total_expenses
    savings_rate = (
        (net / total_income) if total_income > ZERO else None
    )
    by_category = []
    for category, bucket in sorted(
        category_totals.items(), key=lambda item: item[1]["amount"], reverse=True
    ):
        share = (
            bucket["amount"] / total_expenses if total_expenses > ZERO else ZERO
        )
        by_category.append(
            {
                "category": category,
                "count": bucket["count"],
                "amount": money_text(bucket["amount"]),
                "share": ratio_text(share),
            }
        )

    month_rows = [
        {
            "month": month,
            "income": money_text(values["income"]),
            "expenses": money_text(values["expenses"]),
            "net": money_text(values["income"] - values["expenses"]),
        }
        for month, values in sorted(monthly.items())
    ]

    return {
        "income": money_text(total_income),
        "expenses": money_text(total_expenses),
        "net_cashflow": money_text(net),
        "savings_rate": ratio_text(savings_rate) if savings_rate is not None else None,
        "by_category": by_category,
        "monthly": month_rows,
        "transaction_count": len(rows),
        "averaging_basis": "30_day_month",
    }


def average_monthly(values: dict[str, Any], days: int) -> tuple[Decimal, Decimal]:
    """Return (income, expenses) normalized to a 30-day month."""
    income = money(values["income"]) * Decimal("30") / Decimal(days)
    expenses = money(values["expenses"]) * Decimal("30") / Decimal(days)
    return income, expenses


def financial_health(
    *,
    cashflow: dict[str, Any],
    days: int,
    liquid_balance: Any,
    monthly_debt_payment: Any,
    credit_limit: Any,
    credit_outstanding: Any,
) -> dict[str, Any]:
    """Transparent 0-100 financial-wellbeing indicator.

    Deliberately not a credit score and not the completed Risk Engine. Component
    scores and weights are exposed so downstream reports can explain every point.
    """
    avg_income, avg_expenses = average_monthly(cashflow, days)
    monthly_surplus = avg_income - avg_expenses
    savings_rate = (
        monthly_surplus / avg_income if avg_income > ZERO else None
    )
    emergency_months = (
        money(liquid_balance) / avg_expenses if avg_expenses > ZERO else None
    )
    debt_payment = money(monthly_debt_payment)
    dti = (debt_payment / avg_income) if avg_income > ZERO else None
    limit = money(credit_limit)
    outstanding = money(credit_outstanding)
    utilization = (outstanding / limit) if limit > ZERO else ZERO

    components: list[dict[str, Any]] = []

    if emergency_months is None:
        liquidity_points = ZERO
        liquidity_reason = "缺少月均支出数据，无法估算应急金月数"
    else:
        liquidity_points = (
            Decimal("30")
            * clamp(emergency_months / Decimal("6"), ZERO, ONE)
        )
        liquidity_reason = f"应急金可覆盖 {emergency_months.quantize(Decimal('0.1'))} 个月"
    components.append(
        _component("应急储备", "30", liquidity_points, liquidity_reason)
    )

    if savings_rate is None:
        savings_points = ZERO
        savings_reason = "缺少收入数据，无法计算储蓄率"
    else:
        savings_points = (
            Decimal("25")
            * clamp(savings_rate / Decimal("0.30"), ZERO, ONE)
        )
        savings_reason = f"月均储蓄率 {percent_text(savings_rate * HUNDRED)}%"
    components.append(
        _component("储蓄能力", "25", savings_points, savings_reason)
    )

    if dti is None:
        debt_points = ZERO
        debt_reason = "缺少收入数据，无法计算债务收入比"
    else:
        debt_points = (
            Decimal("25")
            * clamp(ONE - dti / Decimal("0.36"), ZERO, ONE)
        )
        debt_reason = f"债务收入比 {percent_text(dti * HUNDRED)}%"
    components.append(
        _component("偿债压力", "25", debt_points, debt_reason)
    )

    if limit <= ZERO:
        credit_points = Decimal("20")
        credit_reason = "无循环信用额度"
    else:
        credit_points = (
            Decimal("20")
            * clamp(ONE - utilization / Decimal("0.50"), ZERO, ONE)
        )
        credit_reason = f"信用卡额度使用率 {percent_text(utilization * HUNDRED)}%"
    components.append(
        _component("信用使用", "20", credit_points, credit_reason)
    )

    total = sum(
        (Decimal(component["points"]) for component in components), ZERO
    )
    score = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    grade = _health_grade(score)

    return {
        "score": score,
        "grade": grade,
        "components": components,
        "metrics": {
            "average_monthly_income": money_text(avg_income),
            "average_monthly_expenses": money_text(avg_expenses),
            "average_monthly_surplus": money_text(monthly_surplus),
            "savings_rate": (
                ratio_text(savings_rate) if savings_rate is not None else None
            ),
            "liquid_balance": money_text(liquid_balance),
            "emergency_fund_months": (
                f"{emergency_months.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
                if emergency_months is not None
                else None
            ),
            "monthly_debt_payment": money_text(debt_payment),
            "debt_to_income": ratio_text(dti) if dti is not None else None,
            "credit_utilization": ratio_text(utilization),
        },
        "assumptions": [
            "月均收入与支出按 30 天/月、查询区间线性折算。",
            "应急金使用活期/储蓄账户余额，不含信用卡可用额度。",
            "债务月供优先使用调用方传入值，否则汇总模拟贷款月供。",
            "该分数是财务健康提示，不是征信评分、授信决定或风控引擎结论。",
        ],
    }


def _component(
    name: str, weight: str, points: Decimal, rationale: str
) -> dict[str, Any]:
    return {
        "name": name,
        "weight": weight,
        "points": percent_text(points),
        "rationale": rationale,
    }


def _health_grade(score: int) -> str:
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    if score >= 35:
        return "D"
    return "E"


def loan_schedule(
    *,
    principal: Any,
    annual_rate_percent: Any,
    term_months: int,
    repayment_method: str,
) -> dict[str, Any]:
    """Amortization with cents rounding per period."""
    principal_value = money(principal)
    rate = to_decimal(annual_rate_percent, field="annual_rate_percent")
    periods = int(term_months)
    monthly_rate = rate / Decimal("1200")
    scheduled_payment: Decimal | None = None
    scheduled_principal: Decimal | None = None

    if repayment_method == "equal_installment":
        if monthly_rate == ZERO:
            raw_payment = principal_value / Decimal(periods)
        else:
            factor = (ONE + monthly_rate) ** periods
            raw_payment = (
                principal_value * monthly_rate * factor / (factor - ONE)
            )
        scheduled_payment = raw_payment.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if scheduled_payment <= ZERO:
            scheduled_payment = Decimal("0.01")
    elif repayment_method == "equal_principal":
        scheduled_principal = (principal_value / Decimal(periods)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        raise ValueError("unsupported repayment method")

    balance = principal_value
    rows: list[dict[str, Any]] = []
    total_payment = ZERO
    total_interest = ZERO

    for month in range(1, periods + 1):
        interest = (balance * monthly_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if month == periods:
            principal_part = balance
        elif repayment_method == "equal_installment":
            principal_part = min(scheduled_payment - interest, balance)
        else:
            assert scheduled_principal is not None
            principal_part = min(scheduled_principal, balance)

        if principal_part < ZERO:
            principal_part = ZERO
        payment = principal_part + interest
        balance -= principal_part
        if balance < ZERO:
            balance = ZERO
        total_payment += payment
        total_interest += interest
        rows.append(
            {
                "month": month,
                "payment": money_text(payment),
                "principal": money_text(principal_part),
                "interest": money_text(interest),
                "remaining_balance": money_text(balance),
            }
        )

    result = {
        "monthly_payment": (
            money_text(scheduled_payment)
            if scheduled_payment is not None
            else None
        ),
        "first_payment": rows[0]["payment"],
        "last_payment": rows[-1]["payment"],
        "total_payment": money_text(total_payment),
        "total_interest": money_text(total_interest),
        "periods": periods,
    }
    return {
        "loan": {
            "principal": money_text(principal_value),
            "annual_rate_percent": percent_text(rate),
            "term_months": periods,
            "repayment_method": repayment_method,
            "currency": "CNY",
        },
        "result": result,
        "schedule_preview": rows[:12],
        "schedule_truncated": periods > 12,
        "rounding": "每期金额四舍五入到分，末期调整剩余本金",
    }


def portfolio_assumptions(
    allocations: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Weighted return/volatility proxies from fixed mock assumptions."""
    details: list[dict[str, Any]] = []
    expected = ZERO
    volatility = ZERO
    total_weight = ZERO
    for allocation in allocations:
        asset_class = str(allocation["asset_class"])
        if asset_class not in ASSET_ASSUMPTIONS:
            raise ValueError(f"unsupported asset class: {asset_class}")
        weight = to_decimal(allocation["weight"], field="weight")
        if weight < ZERO or weight > ONE:
            raise ValueError("weight must be between 0 and 1")
        assumption = ASSET_ASSUMPTIONS[asset_class]
        asset_expected = to_decimal(
            assumption["expected_annual_return_percent"]
        ) / HUNDRED
        asset_volatility = to_decimal(
            assumption["annual_volatility_percent"]
        ) / HUNDRED
        expected += weight * asset_expected
        # Deliberately no correlation matrix: weighted average volatility is a
        # conservative proxy, not a portfolio-optimisation result.
        volatility += weight * asset_volatility
        total_weight += weight
        details.append(
            {
                "asset_class": asset_class,
                "label": assumption["label"],
                "weight": ratio_text(weight),
                "expected_annual_return_percent": percent_text(
                    asset_expected * HUNDRED
                ),
                "annual_volatility_percent": percent_text(
                    asset_volatility * HUNDRED
                ),
            }
        )

    if abs(total_weight - ONE) > Decimal("0.000001"):
        raise ValueError("allocation weights must sum to 1")

    return {
        "expected_annual_return": expected,
        "annual_volatility": volatility,
        "assumptions": details,
    }


def portfolio_projection(
    *,
    initial_amount: Any,
    monthly_contribution: Any,
    horizon_years: int,
    allocations: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic monthly-compounding illustration, no Monte Carlo."""
    initial = money(initial_amount)
    contribution = money(monthly_contribution)
    years = int(horizon_years)
    allocation_rows = list(allocations)
    assumptions = portfolio_assumptions(allocation_rows)
    expected = assumptions["expected_annual_return"]
    volatility = assumptions["annual_volatility"]
    monthly_rate = expected / Decimal(12)

    value = initial
    contributions = initial
    timeline: list[dict[str, Any]] = []
    for month in range(1, years * 12 + 1):
        value = value * (ONE + monthly_rate) + contribution
        contributions += contribution
        if month % 12 == 0:
            timeline.append(
                {
                    "year": month // 12,
                    "contributions": money_text(contributions),
                    "projected_value": money_text(value),
                }
            )

    conservative_annual = max(
        expected - Decimal("1.645") * volatility,
        Decimal("-0.95"),
    )
    conservative_value = initial
    conservative_monthly = conservative_annual / Decimal(12)
    for _ in range(years * 12):
        conservative_value = (
            conservative_value * (ONE + conservative_monthly) + contribution
        )

    return {
        "assumptions": assumptions["assumptions"],
        "metrics": {
            "expected_annual_return_percent": percent_text(
                expected * HUNDRED
            ),
            "annual_volatility_proxy_percent": percent_text(
                volatility * HUNDRED
            ),
            "total_contributions": money_text(contributions),
            "projected_value": money_text(value),
            "projected_gain": money_text(value - contributions),
            "stress_value": money_text(conservative_value),
            "stress_return_percent": percent_text(
                conservative_annual * HUNDRED
            ),
        },
        "timeline": timeline,
        "model_notes": [
            "按资产类别加权年化收益与波动率，固定模拟假设，不使用随机数。",
            "月复利采用年化收益率除以 12 的名义月利率，月末投入。",
            "未建模资产相关性、税费、申赎费和通胀，结果仅为情景估算。",
            "压力情景为预期收益 - 1.645 倍波动率，不是置信区间保证。",
        ],
    }


def investment_risk(
    *,
    portfolio_value: Any,
    allocations: Iterable[dict[str, Any]],
    horizon_days: int,
    confidence: str,
) -> dict[str, Any]:
    """Advisory market-risk metrics, explicitly distinct from operational risk."""
    value = money(portfolio_value)
    allocation_rows = list(allocations)
    assumptions = portfolio_assumptions(allocation_rows)
    expected = assumptions["expected_annual_return"]
    volatility = assumptions["annual_volatility"]
    z_scores = {
        "0.90": Decimal("1.282"),
        "0.95": Decimal("1.645"),
        "0.99": Decimal("2.326"),
    }
    z = z_scores[confidence]
    horizon = Decimal(int(horizon_days)) / Decimal("365")
    scale = horizon.sqrt()
    expected_horizon = expected * horizon
    var_percent = max(
        ZERO, z * volatility * scale - expected_horizon
    )
    var_amount = value * var_percent
    weights = [
        to_decimal(item["weight"], field="weight")
        for item in allocation_rows
    ]
    hhi = sum((weight * weight for weight in weights), ZERO)
    largest = max(weights) if weights else ZERO
    volatility_level = _risk_level(volatility)
    flags: list[str] = []
    if largest > Decimal("0.60"):
        flags.append("single_asset_concentration_above_60pct")
    crypto_weight = sum(
        (
            to_decimal(item["weight"], field="weight")
            for item in allocation_rows
            if item["asset_class"] == "crypto"
        ),
        ZERO,
    )
    if crypto_weight > Decimal("0.10"):
        flags.append("high_volatility_asset_above_10pct")

    return {
        "risk_domain": "market_risk_advisory",
        "metrics": {
            "portfolio_value": money_text(value),
            "horizon_days": int(horizon_days),
            "confidence": confidence,
            "expected_horizon_return_percent": percent_text(
                expected_horizon * HUNDRED
            ),
            "value_at_risk_percent": percent_text(var_percent * HUNDRED),
            "value_at_risk_amount": money_text(var_amount),
            "annual_volatility_proxy_percent": percent_text(
                volatility * HUNDRED
            ),
            "concentration_hhi": ratio_text(hhi),
            "largest_weight": ratio_text(largest),
            "advisory_risk_level": volatility_level,
        },
        "flags": flags,
        "assumptions": assumptions["assumptions"],
        "model_notes": [
            "采用固定模拟资本市场假设的参数法 VaR，不含随机模拟。",
            "波动率为加权平均代理值，未建模资产相关性，可能高估分散化收益。",
            "这是投资组合的市场风险测算，不是银行运营风险决策。",
            "结果不构成投资建议，也不参与或替代任何交易授权。",
        ],
    }


def _risk_level(volatility: Decimal) -> str:
    if volatility <= Decimal("0.05"):
        return "low"
    if volatility <= Decimal("0.12"):
        return "moderate"
    if volatility <= Decimal("0.25"):
        return "high"
    return "very_high"
