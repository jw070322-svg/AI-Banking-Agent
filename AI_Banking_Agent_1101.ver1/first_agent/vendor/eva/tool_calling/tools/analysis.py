"""Cash-flow, financial-wellbeing, and market-risk analysis tools."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from ...data import TODAY
from ..calculations import (
    ASSET_CLASSES,
    average_monthly,
    cashflow_summary,
    financial_health,
    investment_risk,
)
from ..errors import INVALID_ARGUMENTS, ToolLayerError
from ..models import ToolCallContext, ToolDefinition
from ..schema import (
    array_schema,
    boolean_schema,
    integer_schema,
    money_schema,
    object_schema,
    string_schema,
)
from ..services import ToolServices
from ..utils import money_text, now_iso, percent_text, ratio_text, to_decimal


BANK_SOURCE = "MockBank.accounts + MockBank.transactions (demo data)"
ASSUMPTION_SOURCE = "Fixed mock capital-market assumptions v1 (Module 6)"


def register(registry: Any, services: ToolServices) -> None:
    registry.register(_cashflow_definition(services))
    registry.register(_health_definition(services))
    registry.register(_investment_risk_definition())


def _cashflow_definition(services: ToolServices) -> ToolDefinition:
    category_schema = object_schema(
        {
            "category": string_schema(),
            "count": integer_schema(minimum=1),
            "amount": money_schema(),
            "share": string_schema(format="decimal"),
        },
        required=["category", "count", "amount", "share"],
    )
    month_schema = object_schema(
        {
            "month": string_schema(format="year-month"),
            "income": money_schema(),
            "expenses": money_schema(),
            "net": money_schema(),
        },
        required=["month", "income", "expenses", "net"],
    )
    output_schema = object_schema(
        {
            "summary": string_schema(),
            "currency": string_schema(),
            "scope": object_schema(
                {
                    "account_ids": array_schema(string_schema(), min_items=1),
                    "account_count": integer_schema(minimum=1),
                },
                required=["account_ids", "account_count"],
            ),
            "period": object_schema(
                {
                    "from_date": string_schema(format="date"),
                    "to_date": string_schema(format="date"),
                    "days": integer_schema(minimum=1),
                },
                required=["from_date", "to_date", "days"],
            ),
            "metrics": object_schema(
                {
                    "income": money_schema(),
                    "expenses": money_schema(),
                    "net_cashflow": money_schema(),
                    "savings_rate": string_schema(
                        format="decimal", nullable=True
                    ),
                    "average_monthly_income": money_schema(),
                    "average_monthly_expenses": money_schema(),
                    "transaction_count": integer_schema(minimum=0),
                    "averaging_basis": string_schema(),
                },
                required=[
                    "income",
                    "expenses",
                    "net_cashflow",
                    "savings_rate",
                    "average_monthly_income",
                    "average_monthly_expenses",
                    "transaction_count",
                    "averaging_basis",
                ],
            ),
            "by_category": array_schema(category_schema),
            "monthly": array_schema(month_schema),
            "assumptions": array_schema(string_schema()),
            "as_of": string_schema(),
        },
        required=[
            "summary",
            "currency",
            "scope",
            "period",
            "metrics",
            "by_category",
            "monthly",
            "assumptions",
            "as_of",
        ],
    )

    def handler(
        arguments: dict[str, Any], context: ToolCallContext
    ) -> dict[str, Any]:
        days = int(arguments.get("days", 90))
        include_transfers = bool(arguments.get("include_transfers", False))
        accounts = services.bank_access.resolve_accounts(
            context.user_id, arguments.get("account_ref")
        )
        rows = services.bank_access.transactions(accounts, days=days)
        summary_data = cashflow_summary(
            rows, include_transfers=include_transfers
        )
        avg_income, avg_expenses = average_monthly(summary_data, days)
        savings_rate = summary_data["savings_rate"]
        if savings_rate is None:
            rate_text = "无可计算储蓄率"
        else:
            rate_text = f"储蓄率 {percent_text(Decimal(savings_rate) * 100)}%"
        summary = (
            f"近 {days} 天收入 ¥{Decimal(summary_data['income']):,.2f}，"
            f"支出 ¥{Decimal(summary_data['expenses']):,.2f}，"
            f"净现金流 ¥{Decimal(summary_data['net_cashflow']):,.2f}，{rate_text}。"
        )
        from_date = TODAY - timedelta(days=days)
        return {
            "summary": summary,
            "currency": "CNY",
            "scope": {
                "account_ids": sorted(
                    account["account_id"] for account in accounts
                ),
                "account_count": len(accounts),
            },
            "period": {
                "from_date": from_date.isoformat(),
                "to_date": TODAY.isoformat(),
                "days": days,
            },
            "metrics": {
                "income": summary_data["income"],
                "expenses": summary_data["expenses"],
                "net_cashflow": summary_data["net_cashflow"],
                "savings_rate": savings_rate,
                "average_monthly_income": money_text(avg_income),
                "average_monthly_expenses": money_text(avg_expenses),
                "transaction_count": summary_data["transaction_count"],
                "averaging_basis": summary_data["averaging_basis"],
            },
            "by_category": summary_data["by_category"],
            "monthly": summary_data["monthly"],
            "assumptions": [
                (
                    "包含内部转账流水。"
                    if include_transfers
                    else "默认排除类别为“转账”的内部资金划转，避免收入和支出重复计算。"
                ),
                "查询区间按包含今日的自然日计算，月均值按 30 天/月线性折算。",
            ],
            "as_of": now_iso(),
        }

    return ToolDefinition(
        name="analyze_cashflow",
        description=(
            "基于指定账户（或全部账户）的流水计算收入、支出、净现金流、储蓄率、"
            "类别占比和逐月趋势。默认排除内部转账。"
        ),
        category="analysis",
        handler=handler,
        input_schema=object_schema(
            {
                "account_ref": string_schema(
                    "可选账户引用；省略时分析当前客户全部账户。",
                    min_length=1,
                    max_length=32,
                ),
                "days": integer_schema(
                    "分析最近 N 天，默认 90。",
                    minimum=1,
                    maximum=365,
                    default=90,
                ),
                "include_transfers": boolean_schema(
                    "是否把类别为“转账”的流水计入收支，默认否。",
                    default=False,
                ),
            },
            required=[],
        ),
        output_schema=output_schema,
        mutating=False,
        risk_tier="R2",
        permissions=("transactions:read",),
        implementation_status="mocked",
        data_sources=(BANK_SOURCE,),
        simulated=True,
        tags=("cashflow", "savings", "analysis", "read-only"),
    )


def _health_definition(services: ToolServices) -> ToolDefinition:
    component_schema = object_schema(
        {
            "name": string_schema(),
            "weight": string_schema(format="decimal"),
            "points": string_schema(format="decimal"),
            "rationale": string_schema(),
        },
        required=["name", "weight", "points", "rationale"],
    )
    output_schema = object_schema(
        {
            "summary": string_schema(),
            "score": integer_schema(minimum=0, maximum=100),
            "grade": string_schema(enum=["A", "B", "C", "D", "E"]),
            "components": array_schema(component_schema, min_items=4, max_items=4),
            "metrics": object_schema(
                {
                    "average_monthly_income": money_schema(),
                    "average_monthly_expenses": money_schema(),
                    "average_monthly_surplus": money_schema(),
                    "savings_rate": string_schema(
                        format="decimal", nullable=True
                    ),
                    "liquid_balance": money_schema(),
                    "emergency_fund_months": string_schema(
                        format="decimal", nullable=True
                    ),
                    "monthly_debt_payment": money_schema(),
                    "debt_to_income": string_schema(
                        format="decimal", nullable=True
                    ),
                    "credit_utilization": string_schema(format="decimal"),
                },
                required=[
                    "average_monthly_income",
                    "average_monthly_expenses",
                    "average_monthly_surplus",
                    "savings_rate",
                    "liquid_balance",
                    "emergency_fund_months",
                    "monthly_debt_payment",
                    "debt_to_income",
                    "credit_utilization",
                ],
            ),
            "assumptions": array_schema(string_schema()),
            "limitations": array_schema(string_schema()),
            "period": object_schema(
                {
                    "from_date": string_schema(format="date"),
                    "to_date": string_schema(format="date"),
                    "days": integer_schema(minimum=1),
                },
                required=["from_date", "to_date", "days"],
            ),
            "as_of": string_schema(),
        },
        required=[
            "summary",
            "score",
            "grade",
            "components",
            "metrics",
            "assumptions",
            "limitations",
            "period",
            "as_of",
        ],
    )

    def handler(
        arguments: dict[str, Any], context: ToolCallContext
    ) -> dict[str, Any]:
        days = int(arguments.get("days", 90))
        accounts = services.bank_access.resolve_accounts(
            context.user_id, arguments.get("account_ref")
        )
        rows = services.bank_access.transactions(accounts, days=days)
        cashflow = cashflow_summary(rows, include_transfers=False)
        provided_debt = arguments.get("monthly_debt_payment")
        if provided_debt is not None:
            debt_payment = to_decimal(
                provided_debt, field="monthly_debt_payment"
            )
            if debt_payment < 0:
                raise ToolLayerError(
                    INVALID_ARGUMENTS,
                    "monthly_debt_payment 不能为负数。",
                )
        else:
            debt_payment = sum(
                (
                    loan["monthly_payment"]
                    for loan in services.bank_access.loans(context.user_id)
                ),
                Decimal("0.00"),
            )
        credit_limit, credit_outstanding = services.bank_access.credit_totals(
            accounts
        )
        result = financial_health(
            cashflow=cashflow,
            days=days,
            liquid_balance=services.bank_access.liquid_balance(accounts),
            monthly_debt_payment=debt_payment,
            credit_limit=credit_limit,
            credit_outstanding=credit_outstanding,
        )
        from_date = TODAY - timedelta(days=days)
        return {
            "summary": (
                f"财务健康提示分 {result['score']}/100（{result['grade']} 级）；"
                "该分数不是征信评分或风控结论。"
            ),
            **result,
            "limitations": [
                "基于模拟账户与流水，不能代表真实银行的授信或风险判断。",
                "未考虑资产价格波动、税务、家庭负债细节和未来收入变化。",
                "分数仅用于解释性演示，不应作为产品推荐或贷款审批依据。",
            ],
            "period": {
                "from_date": from_date.isoformat(),
                "to_date": TODAY.isoformat(),
                "days": days,
            },
            "as_of": now_iso(),
        }

    return ToolDefinition(
        name="calculate_financial_health",
        description=(
            "计算透明的 0-100 财务健康提示分，拆解应急储备、储蓄能力、偿债压力、"
            "信用使用四项。它不是征信评分，也不调用或替代 Risk Engine。"
        ),
        category="analysis",
        handler=handler,
        input_schema=object_schema(
            {
                "account_ref": string_schema(
                    "可选账户引用；省略时分析当前客户全部账户。",
                    min_length=1,
                    max_length=32,
                ),
                "days": integer_schema(
                    "现金流观察窗口，默认 90 天。",
                    minimum=30,
                    maximum=365,
                    default=90,
                ),
                "monthly_debt_payment": money_schema(
                    "可选月供（含贷款/分期）；省略时使用模拟贷款月供。",
                ),
            },
            required=[],
        ),
        output_schema=output_schema,
        mutating=False,
        risk_tier="R2",
        permissions=("analysis:read",),
        implementation_status="mocked",
        data_sources=(BANK_SOURCE, "Transparent Module 6 scoring formula v1"),
        simulated=True,
        tags=("financial-health", "wellbeing", "analysis", "read-only"),
    )


def _investment_risk_definition() -> ToolDefinition:
    allocation_schema = object_schema(
        {
            "asset_class": string_schema(enum=list(ASSET_CLASSES)),
            "weight": string_schema(
                "组合权重，0-1 的小数，所有资产权重之和必须为 1。",
                format="decimal",
            ),
        },
        required=["asset_class", "weight"],
    )
    output_schema = object_schema(
        {
            "summary": string_schema(),
            "risk_domain": string_schema(enum=["market_risk_advisory"]),
            "metrics": object_schema(
                {
                    "portfolio_value": money_schema(),
                    "horizon_days": integer_schema(minimum=1),
                    "confidence": string_schema(enum=["0.90", "0.95", "0.99"]),
                    "expected_horizon_return_percent": string_schema(
                        format="decimal"
                    ),
                    "value_at_risk_percent": string_schema(format="decimal"),
                    "value_at_risk_amount": money_schema(),
                    "annual_volatility_proxy_percent": string_schema(
                        format="decimal"
                    ),
                    "concentration_hhi": string_schema(format="decimal"),
                    "largest_weight": string_schema(format="decimal"),
                    "advisory_risk_level": string_schema(
                        enum=["low", "moderate", "high", "very_high"]
                    ),
                },
                required=[
                    "portfolio_value",
                    "horizon_days",
                    "confidence",
                    "expected_horizon_return_percent",
                    "value_at_risk_percent",
                    "value_at_risk_amount",
                    "annual_volatility_proxy_percent",
                    "concentration_hhi",
                    "largest_weight",
                    "advisory_risk_level",
                ],
            ),
            "flags": array_schema(string_schema()),
            "assumptions": array_schema(object_schema(
                {
                    "asset_class": string_schema(),
                    "label": string_schema(),
                    "weight": string_schema(format="decimal"),
                    "expected_annual_return_percent": string_schema(
                        format="decimal"
                    ),
                    "annual_volatility_percent": string_schema(
                        format="decimal"
                    ),
                },
                required=[
                    "asset_class",
                    "label",
                    "weight",
                    "expected_annual_return_percent",
                    "annual_volatility_percent",
                ],
            )),
            "model_notes": array_schema(string_schema()),
            "disclaimer": string_schema(),
            "as_of": string_schema(),
        },
        required=[
            "summary",
            "risk_domain",
            "metrics",
            "flags",
            "assumptions",
            "model_notes",
            "disclaimer",
            "as_of",
        ],
    )

    def handler(
        arguments: dict[str, Any], context: ToolCallContext
    ) -> dict[str, Any]:
        allocations = list(arguments["allocations"])
        portfolio_value = to_decimal(
            arguments["portfolio_value"], field="portfolio_value"
        )
        if portfolio_value <= 0:
            raise ToolLayerError(
                INVALID_ARGUMENTS, "portfolio_value 必须大于 0。"
            )
        classes = [item["asset_class"] for item in allocations]
        if len(classes) != len(set(classes)):
            raise ToolLayerError(
                INVALID_ARGUMENTS, "allocations 中不能重复资产类别。"
            )
        try:
            result = investment_risk(
                portfolio_value=portfolio_value,
                allocations=allocations,
                horizon_days=int(arguments.get("horizon_days", 30)),
                confidence=str(arguments.get("confidence", "0.95")),
            )
        except ValueError as exc:
            raise ToolLayerError(INVALID_ARGUMENTS, str(exc)) from exc
        metrics = result["metrics"]
        summary = (
            f"组合市场风险测算：{metrics['confidence']} 置信度、"
            f"{metrics['horizon_days']} 天参数法 VaR 为 "
            f"¥{Decimal(metrics['value_at_risk_amount']):,.2f}"
            f"（{metrics['value_at_risk_percent']}%）。"
            "该结果不是运营风险决策，也不授权任何交易。"
        )
        return {
            "summary": summary,
            **result,
            "disclaimer": (
                "基于固定模拟假设的市场风险测算，不构成投资建议；"
                "与已完成 Risk Engine 的运营风险决策相互独立。"
            ),
            "as_of": now_iso(),
        }

    return ToolDefinition(
        name="calculate_risk",
        description=(
            "使用固定模拟资本市场假设，计算投资组合的加权波动率、集中度和参数法 VaR。"
            "该工具只做市场风险测算，不复制、不替代已完成的运营 Risk Engine，"
            "也不返回任何交易授权。"
        ),
        category="analysis",
        handler=handler,
        input_schema=object_schema(
            {
                "portfolio_value": money_schema("组合当前市值，CNY。"),
                "allocations": array_schema(
                    allocation_schema,
                    min_items=1,
                    max_items=len(ASSET_CLASSES),
                ),
                "horizon_days": integer_schema(
                    "VaR 持有期，默认 30 天。",
                    minimum=1,
                    maximum=365,
                    default=30,
                ),
                "confidence": string_schema(
                    "VaR 置信度。",
                    enum=["0.90", "0.95", "0.99"],
                    default="0.95",
                ),
            },
            required=["portfolio_value", "allocations"],
        ),
        output_schema=output_schema,
        mutating=False,
        risk_tier="R2",
        permissions=("analysis:read",),
        implementation_status="mocked",
        data_sources=(ASSUMPTION_SOURCE,),
        simulated=True,
        tags=(
            "market-risk",
            "var",
            "financial-risk",
            "not-operational-risk-engine",
            "read-only",
        ),
    )
