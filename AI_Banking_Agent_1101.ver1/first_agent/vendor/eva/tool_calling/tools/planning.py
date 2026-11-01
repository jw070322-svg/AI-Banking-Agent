"""Loan, portfolio, budget, and alert tools."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from ..calculations import (
    ASSET_CLASSES,
    loan_schedule,
    portfolio_projection,
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
from ..utils import (
    money,
    money_text,
    new_call_id,
    now_iso,
    ratio_text,
    to_decimal,
)


ALERT_TYPES = ("balance_below", "transaction_above", "budget_threshold")
ALERT_CHANNELS = ("in_app", "sms")


def register(registry: Any, services: ToolServices) -> None:
    registry.register(_loan_definition())
    registry.register(_portfolio_definition())
    registry.register(_budget_definition(services))
    registry.register(_alert_definition(services))


def _loan_definition() -> ToolDefinition:
    schedule_schema = object_schema(
        {
            "month": integer_schema(minimum=1),
            "payment": money_schema(),
            "principal": money_schema(),
            "interest": money_schema(),
            "remaining_balance": money_schema(),
        },
        required=[
            "month",
            "payment",
            "principal",
            "interest",
            "remaining_balance",
        ],
    )
    output_schema = object_schema(
        {
            "summary": string_schema(),
            "loan": object_schema(
                {
                    "principal": money_schema(),
                    "annual_rate_percent": string_schema(format="decimal"),
                    "term_months": integer_schema(minimum=1),
                    "repayment_method": string_schema(
                        enum=["equal_installment", "equal_principal"]
                    ),
                    "currency": string_schema(),
                },
                required=[
                    "principal",
                    "annual_rate_percent",
                    "term_months",
                    "repayment_method",
                    "currency",
                ],
            ),
            "result": object_schema(
                {
                    "monthly_payment": money_schema(nullable=True),
                    "first_payment": money_schema(),
                    "last_payment": money_schema(),
                    "total_payment": money_schema(),
                    "total_interest": money_schema(),
                    "periods": integer_schema(minimum=1),
                },
                required=[
                    "monthly_payment",
                    "first_payment",
                    "last_payment",
                    "total_payment",
                    "total_interest",
                    "periods",
                ],
            ),
            "schedule_preview": array_schema(schedule_schema),
            "schedule_truncated": boolean_schema(),
            "rounding": string_schema(),
            "assumptions": array_schema(string_schema()),
            "disclaimer": string_schema(),
            "as_of": string_schema(),
        },
        required=[
            "summary",
            "loan",
            "result",
            "schedule_preview",
            "schedule_truncated",
            "rounding",
            "assumptions",
            "disclaimer",
            "as_of",
        ],
    )

    def handler(
        arguments: dict[str, Any], context: ToolCallContext
    ) -> dict[str, Any]:
        principal = to_decimal(arguments["principal"], field="principal")
        rate = to_decimal(
            arguments["annual_rate_percent"], field="annual_rate_percent"
        )
        if principal <= 0:
            raise ToolLayerError(INVALID_ARGUMENTS, "principal 必须大于 0。")
        if rate < 0 or rate > 100:
            raise ToolLayerError(
                INVALID_ARGUMENTS,
                "annual_rate_percent 必须在 0 到 100 之间。",
            )
        method = arguments.get("repayment_method", "equal_installment")
        result = loan_schedule(
            principal=money(principal),
            annual_rate_percent=rate,
            term_months=int(arguments["term_months"]),
            repayment_method=method,
        )
        payment = result["result"]
        if method == "equal_installment":
            summary = (
                f"贷款本金 ¥{Decimal(result['loan']['principal']):,.2f}，"
                f"年化 {result['loan']['annual_rate_percent']}%，"
                f"{result['loan']['term_months']} 期等额本息，"
                f"月供 ¥{Decimal(payment['monthly_payment']):,.2f}，"
                f"总利息 ¥{Decimal(payment['total_interest']):,.2f}。"
            )
        else:
            summary = (
                f"贷款本金 ¥{Decimal(result['loan']['principal']):,.2f}，"
                f"年化 {result['loan']['annual_rate_percent']}%，"
                f"{result['loan']['term_months']} 期等额本金，"
                f"首月还款 ¥{Decimal(payment['first_payment']):,.2f}，"
                f"末月 ¥{Decimal(payment['last_payment']):,.2f}。"
            )
        return {
            "summary": summary,
            **result,
            "assumptions": [
                "采用固定年化利率与按月计息，未考虑放款日、利率调整、提前还款和税费。",
                "每期利息按剩余本金计算并四舍五入到分，末期调整剩余本金。",
                "示例结果仅用于测算，不构成贷款报价或授信承诺。",
            ],
            "disclaimer": (
                "真实贷款条件、费率和月供以银行审批及正式合同为准。"
            ),
            "as_of": now_iso(),
        }

    return ToolDefinition(
        name="calculate_loan",
        description=(
            "使用确定性摊还公式计算等额本息或等额本金的月供、总利息和分期预览。"
            "输入必须由调用方给出；结果不是贷款审批或真实报价。"
        ),
        category="planning",
        handler=handler,
        input_schema=object_schema(
            {
                "principal": money_schema("贷款本金，CNY。"),
                "annual_rate_percent": string_schema(
                    "年化利率百分数，例如 4.80。",
                    format="decimal",
                ),
                "term_months": integer_schema(
                    "贷款期数（月）。",
                    minimum=1,
                    maximum=480,
                ),
                "repayment_method": string_schema(
                    "还款方式。",
                    enum=["equal_installment", "equal_principal"],
                    default="equal_installment",
                ),
            },
            required=["principal", "annual_rate_percent", "term_months"],
        ),
        output_schema=output_schema,
        mutating=False,
        risk_tier="R2",
        permissions=("analysis:read",),
        implementation_status="implemented",
        data_sources=("User-supplied inputs", "Deterministic amortization v1"),
        simulated=False,
        tags=("loan", "amortization", "calculator", "read-only"),
    )


def _portfolio_definition() -> ToolDefinition:
    allocation_schema = object_schema(
        {
            "asset_class": string_schema(enum=list(ASSET_CLASSES)),
            "weight": string_schema(
                "组合权重，0-1 小数，总和必须为 1。",
                format="decimal",
            ),
        },
        required=["asset_class", "weight"],
    )
    assumption_schema = object_schema(
        {
            "asset_class": string_schema(),
            "label": string_schema(),
            "weight": string_schema(format="decimal"),
            "expected_annual_return_percent": string_schema(format="decimal"),
            "annual_volatility_percent": string_schema(format="decimal"),
        },
        required=[
            "asset_class",
            "label",
            "weight",
            "expected_annual_return_percent",
            "annual_volatility_percent",
        ],
    )
    timeline_schema = object_schema(
        {
            "year": integer_schema(minimum=1),
            "contributions": money_schema(),
            "projected_value": money_schema(),
        },
        required=["year", "contributions", "projected_value"],
    )
    output_schema = object_schema(
        {
            "summary": string_schema(),
            "inputs": object_schema(
                {
                    "initial_amount": money_schema(),
                    "monthly_contribution": money_schema(),
                    "horizon_years": integer_schema(minimum=1),
                    "allocations": array_schema(allocation_schema),
                    "currency": string_schema(),
                },
                required=[
                    "initial_amount",
                    "monthly_contribution",
                    "horizon_years",
                    "allocations",
                    "currency",
                ],
            ),
            "assumptions": array_schema(assumption_schema),
            "metrics": object_schema(
                {
                    "expected_annual_return_percent": string_schema(
                        format="decimal"
                    ),
                    "annual_volatility_proxy_percent": string_schema(
                        format="decimal"
                    ),
                    "total_contributions": money_schema(),
                    "projected_value": money_schema(),
                    "projected_gain": money_schema(),
                    "stress_value": money_schema(),
                    "stress_return_percent": string_schema(format="decimal"),
                },
                required=[
                    "expected_annual_return_percent",
                    "annual_volatility_proxy_percent",
                    "total_contributions",
                    "projected_value",
                    "projected_gain",
                    "stress_value",
                    "stress_return_percent",
                ],
            ),
            "timeline": array_schema(timeline_schema),
            "model_notes": array_schema(string_schema()),
            "disclaimer": string_schema(),
            "as_of": string_schema(),
        },
        required=[
            "summary",
            "inputs",
            "assumptions",
            "metrics",
            "timeline",
            "model_notes",
            "disclaimer",
            "as_of",
        ],
    )

    def handler(
        arguments: dict[str, Any], context: ToolCallContext
    ) -> dict[str, Any]:
        initial = to_decimal(
            arguments["initial_amount"], field="initial_amount"
        )
        monthly = to_decimal(
            arguments.get("monthly_contribution", "0.00"),
            field="monthly_contribution",
        )
        if initial < 0 or monthly < 0:
            raise ToolLayerError(
                INVALID_ARGUMENTS,
                "initial_amount 与 monthly_contribution 不能为负数。",
            )
        if initial == 0 and monthly == 0:
            raise ToolLayerError(
                INVALID_ARGUMENTS,
                "初始金额与每月投入不能同时为 0。",
            )
        allocations = list(arguments["allocations"])
        classes = [item["asset_class"] for item in allocations]
        if len(classes) != len(set(classes)):
            raise ToolLayerError(
                INVALID_ARGUMENTS, "allocations 中不能重复资产类别。"
            )
        try:
            result = portfolio_projection(
                initial_amount=initial,
                monthly_contribution=monthly,
                horizon_years=int(arguments["horizon_years"]),
                allocations=allocations,
            )
        except ValueError as exc:
            raise ToolLayerError(INVALID_ARGUMENTS, str(exc)) from exc
        metrics = result["metrics"]
        summary = (
            f"{arguments['horizon_years']} 年模拟测算：总投入 "
            f"¥{Decimal(metrics['total_contributions']):,.2f}，"
            f"预期情景价值 ¥{Decimal(metrics['projected_value']):,.2f}，"
            f"压力情景 ¥{Decimal(metrics['stress_value']):,.2f}。"
            "结果基于固定模拟假设，不保证实现。"
        )
        return {
            "summary": summary,
            "inputs": {
                "initial_amount": money_text(initial),
                "monthly_contribution": money_text(monthly),
                "horizon_years": int(arguments["horizon_years"]),
                "allocations": [
                    {
                        "asset_class": item["asset_class"],
                        "weight": ratio_text(item["weight"]),
                    }
                    for item in allocations
                ],
                "currency": "CNY",
            },
            "assumptions": result["assumptions"],
            "metrics": result["metrics"],
            "timeline": result["timeline"],
            "model_notes": result["model_notes"],
            "disclaimer": (
                "该工具不读取真实行情，不执行交易；所有收益与压力情景均为模拟。"
                "不构成投资建议。"
            ),
            "as_of": now_iso(),
        }

    return ToolDefinition(
        name="calculate_portfolio",
        description=(
            "根据用户给定的初始金额、每月投入、期限和资产配置，计算固定假设下的"
            "确定性组合增长和压力情景。不读取真实行情、不使用随机数、不执行投资。"
        ),
        category="planning",
        handler=handler,
        input_schema=object_schema(
            {
                "initial_amount": money_schema("初始投入金额，CNY，可为 0。"),
                "monthly_contribution": money_schema(
                    "每月末投入金额，CNY，默认 0。",
                    default="0.00",
                ),
                "horizon_years": integer_schema(
                    "投资期限（年），默认 10。",
                    minimum=1,
                    maximum=40,
                    default=10,
                ),
                "allocations": array_schema(
                    allocation_schema,
                    min_items=1,
                    max_items=len(ASSET_CLASSES),
                ),
            },
            required=["initial_amount", "allocations"],
        ),
        output_schema=output_schema,
        mutating=False,
        risk_tier="R2",
        permissions=("analysis:read",),
        implementation_status="mocked",
        data_sources=(
            "User-supplied inputs",
            "Fixed mock capital-market assumptions v1 (Module 6)",
        ),
        simulated=True,
        tags=("portfolio", "projection", "mocked-assumptions", "read-only"),
    )


def _budget_definition(services: ToolServices) -> ToolDefinition:
    category_schema = object_schema(
        {
            "category": string_schema(min_length=1, max_length=20),
            "limit": money_schema(),
        },
        required=["category", "limit"],
    )
    created_category_schema = object_schema(
        {
            "category": string_schema(),
            "limit": money_schema(),
            "income_share": string_schema(format="decimal"),
        },
        required=["category", "limit", "income_share"],
    )
    output_schema = object_schema(
        {
            "summary": string_schema(),
            "budget_id": string_schema(),
            "name": string_schema(),
            "month": string_schema(format="year-month"),
            "currency": string_schema(),
            "monthly_income": money_schema(),
            "total_budgeted": money_schema(),
            "unallocated": money_schema(),
            "status": string_schema(enum=["active"]),
            "categories": array_schema(
                created_category_schema, min_items=1, max_items=20
            ),
            "created_at": string_schema(),
            "persistence_mode": string_schema(enum=["in_memory_mock"]),
            "notes": array_schema(string_schema()),
            "as_of": string_schema(),
        },
        required=[
            "summary",
            "budget_id",
            "name",
            "month",
            "currency",
            "monthly_income",
            "total_budgeted",
            "unallocated",
            "status",
            "categories",
            "created_at",
            "persistence_mode",
            "notes",
            "as_of",
        ],
    )

    def handler(
        arguments: dict[str, Any], context: ToolCallContext
    ) -> dict[str, Any]:
        income = money(arguments["monthly_income"])
        if income <= 0:
            raise ToolLayerError(
                INVALID_ARGUMENTS, "monthly_income 必须大于 0。"
            )
        raw_categories = list(arguments["categories"])
        seen: set[str] = set()
        categories = []
        total = Decimal("0.00")
        for item in raw_categories:
            label = item["category"].strip()
            if not label:
                raise ToolLayerError(
                    INVALID_ARGUMENTS, "预算类别名称不能为空。"
                )
            if label in seen:
                raise ToolLayerError(
                    INVALID_ARGUMENTS, f"预算类别「{label}」重复。"
                )
            seen.add(label)
            limit = money(item["limit"])
            if limit <= 0:
                raise ToolLayerError(
                    INVALID_ARGUMENTS, "每个预算类别的金额必须大于 0。"
                )
            total += limit
            categories.append(
                {
                    "category": label,
                    "limit": money_text(limit),
                    "income_share": ratio_text(limit / income),
                }
            )
        unallocated = income - total
        month = arguments.get("month") or date.today().strftime("%Y-%m")
        budget_id = f"BDG-{new_call_id().split('-', 1)[1]}"
        created_at = now_iso()
        name = (arguments.get("name") or "月度预算").strip()[:60]
        record = {
            "budget_id": budget_id,
            "user_id": context.user_id,
            "name": name,
            "month": month,
            "currency": "CNY",
            "monthly_income": money_text(income),
            "total_budgeted": money_text(total),
            "unallocated": money_text(unallocated),
            "status": "active",
            "categories": categories,
            "created_at": created_at,
            "persistence_mode": "in_memory_mock",
        }
        services.planning.save_budget(record)
        warning = (
            "预算总额超过月收入，未分配金额为负。"
            if unallocated < 0
            else f"未分配金额 ¥{unallocated:,.2f}。"
        )
        return {
            "summary": (
                f"已创建 {month} 预算《{name}》，分配 "
                f"¥{total:,.2f} / 收入 ¥{income:,.2f}；{warning}"
            ),
            **{key: record[key] for key in (
                "budget_id",
                "name",
                "month",
                "currency",
                "monthly_income",
                "total_budgeted",
                "unallocated",
                "status",
                "categories",
                "created_at",
                "persistence_mode",
            )},
            "notes": [
                "预算仅保存在当前进程内存中，重启后丢失。",
                "本原型不会创建真实银行预算、扣款计划或自动转账。",
            ],
            "as_of": now_iso(),
        }

    return ToolDefinition(
        name="create_budget",
        description=(
            "创建一个内存中的月度预算并校验收入/类别金额。该操作改变模块状态，"
            "必须由外层提供明确确认和幂等键；不触发任何真实银行扣款。"
        ),
        category="planning",
        handler=handler,
        input_schema=object_schema(
            {
                "monthly_income": money_schema("月收入，CNY。"),
                "categories": array_schema(
                    category_schema, min_items=1, max_items=20
                ),
                "name": string_schema(
                    "可选预算名称。",
                    max_length=60,
                ),
                "month": string_schema(
                    "可选预算月份，YYYY-MM；省略时使用当月。",
                    format="year-month",
                ),
            },
            required=["monthly_income", "categories"],
        ),
        output_schema=output_schema,
        mutating=True,
        risk_tier="R3",
        permissions=("planning:write",),
        requires_confirmation=True,
        implementation_status="mocked",
        data_sources=(
            "User-supplied inputs",
            "In-memory PlanningStore (non-durable mock)",
        ),
        simulated=True,
        tags=("budget", "planning", "state-changing", "in-memory"),
    )


def _alert_definition(services: ToolServices) -> ToolDefinition:
    output_schema = object_schema(
        {
            "summary": string_schema(),
            "alert_id": string_schema(),
            "alert_type": string_schema(enum=list(ALERT_TYPES)),
            "threshold": money_schema(),
            "account": object_schema(
                {
                    "account_id": string_schema(),
                    "account_type": string_schema(),
                    "last4": string_schema(pattern=r"^\d{4}$"),
                },
                required=["account_id", "account_type", "last4"],
                nullable=True,
            ),
            "channel": string_schema(enum=list(ALERT_CHANNELS)),
            "status": string_schema(enum=["active"]),
            "delivery": object_schema(
                {
                    "mode": string_schema(enum=["mock_not_sent"]),
                    "sent": boolean_schema(),
                    "message": string_schema(),
                },
                required=["mode", "sent", "message"],
            ),
            "created_at": string_schema(),
            "persistence_mode": string_schema(enum=["in_memory_mock"]),
            "notes": array_schema(string_schema()),
            "as_of": string_schema(),
        },
        required=[
            "summary",
            "alert_id",
            "alert_type",
            "threshold",
            "account",
            "channel",
            "status",
            "delivery",
            "created_at",
            "persistence_mode",
            "notes",
            "as_of",
        ],
    )

    def handler(
        arguments: dict[str, Any], context: ToolCallContext
    ) -> dict[str, Any]:
        alert_type = arguments["alert_type"]
        threshold = money(arguments["threshold"])
        if threshold <= 0:
            raise ToolLayerError(
                INVALID_ARGUMENTS, "threshold 必须大于 0。"
            )
        account_ref = arguments.get("account_ref") or None
        if alert_type == "balance_below" and not account_ref:
            raise ToolLayerError(
                INVALID_ARGUMENTS,
                "balance_below 提醒必须指定 account_ref。",
            )
        account = None
        if account_ref:
            selected = services.bank_access.resolve_accounts(
                context.user_id, account_ref
            )[0]
            account = {
                "account_id": selected["account_id"],
                "account_type": selected["type"],
                "last4": selected["last4"],
            }
        alert_id = f"ALT-{new_call_id().split('-', 1)[1]}"
        created_at = now_iso()
        channel = arguments.get("channel", "in_app")
        record = {
            "alert_id": alert_id,
            "user_id": context.user_id,
            "alert_type": alert_type,
            "threshold": money_text(threshold),
            "account": account,
            "channel": channel,
            "status": "active",
            "delivery": {
                "mode": "mock_not_sent",
                "sent": False,
                "message": "本原型只保存提醒规则，不发送真实短信或推送。",
            },
            "created_at": created_at,
            "persistence_mode": "in_memory_mock",
        }
        services.planning.save_alert(record)
        note = (arguments.get("note") or "").strip()
        return {
            "summary": (
                f"已创建 {alert_type} 提醒，阈值 ¥{threshold:,.2f}；"
                "规则保存在内存中，未发送真实通知。"
            ),
            **{key: record[key] for key in (
                "alert_id",
                "alert_type",
                "threshold",
                "account",
                "channel",
                "status",
                "delivery",
                "created_at",
                "persistence_mode",
            )},
            "notes": [
                "提醒规则仅保存在当前进程内存中，重启后丢失。",
                "未连接短信/推送服务，delivery.sent 始终为 false。",
                "本原型不包含后台监控/触发引擎，规则不会自动评估。",
                *(["备注：" + note] if note else []),
            ],
            "as_of": now_iso(),
        }

    return ToolDefinition(
        name="create_alert",
        description=(
            "创建一个内存中的余额/交易/预算提醒规则。该操作改变模块状态，"
            "必须由外层提供明确确认和幂等键；不会发送真实通知。"
        ),
        category="planning",
        handler=handler,
        input_schema=object_schema(
            {
                "alert_type": string_schema(
                    "提醒类型。",
                    enum=list(ALERT_TYPES),
                ),
                "threshold": money_schema("提醒阈值，CNY。"),
                "account_ref": string_schema(
                    "可选账户引用；balance_below 必填。",
                    min_length=1,
                    max_length=32,
                ),
                "channel": string_schema(
                    "提醒渠道（仅记录，不实际发送）。",
                    enum=list(ALERT_CHANNELS),
                    default="in_app",
                ),
                "note": string_schema(
                    "可选备注。",
                    max_length=140,
                ),
            },
            required=["alert_type", "threshold"],
        ),
        output_schema=output_schema,
        mutating=True,
        risk_tier="R3",
        permissions=("planning:write",),
        requires_confirmation=True,
        implementation_status="mocked",
        data_sources=(
            "User-supplied inputs",
            "In-memory PlanningStore (non-durable mock)",
        ),
        simulated=True,
        tags=("alert", "planning", "state-changing", "in-memory"),
    )
