"""Account and transaction retrieval tools."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from ...data import TODAY
from ..models import ToolCallContext, ToolDefinition
from ..schema import (
    array_schema,
    integer_schema,
    money_schema,
    object_schema,
    string_schema,
)
from ..services import ToolServices
from ..utils import money_text, now_iso


ACCOUNT_SOURCE = "MockBank.accounts (in-memory demo data)"
TRANSACTION_SOURCE = "MockBank.transactions (deterministic demo data)"


def register(registry: Any, services: ToolServices) -> None:
    registry.register(_balance_definition(services))
    registry.register(_transactions_definition(services))


def _balance_definition(services: ToolServices) -> ToolDefinition:
    output_account = object_schema(
        {
            "account_id": string_schema(),
            "account_type": string_schema(),
            "last4": string_schema(pattern=r"^\d{4}$"),
            "kind": string_schema(enum=["debit", "credit"]),
            "currency": string_schema(),
            "status": string_schema(),
            "balance": money_schema(),
            "available": money_schema(),
            "credit_limit": money_schema(),
            "outstanding": money_schema(),
            "available_credit": money_schema(),
        },
        required=[
            "account_id",
            "account_type",
            "last4",
            "kind",
            "currency",
            "status",
        ],
    )
    output_schema = object_schema(
        {
            "summary": string_schema(),
            "count": integer_schema(minimum=1),
            "accounts": array_schema(output_account, min_items=1),
            "as_of": string_schema(),
        },
        required=["summary", "count", "accounts", "as_of"],
    )

    def handler(
        arguments: dict[str, Any], context: ToolCallContext
    ) -> dict[str, Any]:
        accounts = services.bank_access.resolve_accounts(
            context.user_id, arguments.get("account_ref")
        )
        serialized = []
        for account in accounts:
            base = {
                "account_id": account["account_id"],
                "account_type": account["type"],
                "last4": account["last4"],
                "kind": account["kind"],
                "currency": account["currency"],
                "status": account["status"],
            }
            if account["kind"] == "credit":
                base.update(
                    {
                        "credit_limit": money_text(account["credit_limit"]),
                        "outstanding": money_text(account["outstanding"]),
                        "available_credit": money_text(
                            account["available_credit"]
                        ),
                    }
                )
            else:
                base.update(
                    {
                        "balance": money_text(account["balance"]),
                        "available": money_text(account["available"]),
                    }
                )
            serialized.append(base)

        if len(serialized) == 1:
            item = serialized[0]
            if item["kind"] == "credit":
                summary = (
                    f"{item['account_type']}（尾号 {item['last4']}）"
                    f"可用额度 ¥{item['available_credit']}，已用 ¥{item['outstanding']}。"
                )
            else:
                summary = (
                    f"{item['account_type']}（尾号 {item['last4']}）"
                    f"可用余额 ¥{item['available']}。"
                )
        else:
            liquid = sum(
                (
                    Decimal(item["available"])
                    for item in serialized
                    if item["kind"] == "debit"
                ),
                Decimal("0.00"),
            )
            summary = (
                f"查询到 {len(serialized)} 个账户，储蓄类可用资金合计 "
                f"¥{liquid:,.2f}。"
            )
        return {
            "summary": summary,
            "count": len(serialized),
            "accounts": serialized,
            "as_of": now_iso(),
        }

    return ToolDefinition(
        name="get_account_balance",
        description=(
            "查询当前登录客户名下账户的余额/可用额度。账户引用可为别名、尾号或不透明 ID；"
            "不接受完整卡号，也不能跨客户查询。"
        ),
        category="accounts",
        handler=handler,
        input_schema=object_schema(
            {
                "account_ref": string_schema(
                    "账户别名、尾号或不透明账户 ID；省略时查询全部账户。",
                    min_length=1,
                    max_length=32,
                )
            },
            required=[],
            description="Current-customer account balance query.",
        ),
        output_schema=output_schema,
        mutating=False,
        risk_tier="R1",
        permissions=("account:read",),
        implementation_status="mocked",
        data_sources=(ACCOUNT_SOURCE,),
        simulated=True,
        tags=("account", "balance", "read-only"),
    )


def _transactions_definition(services: ToolServices) -> ToolDefinition:
    transaction_item = object_schema(
        {
            "tx_id": string_schema(),
            "date": string_schema(format="date"),
            "merchant": string_schema(),
            "category": string_schema(),
            "direction": string_schema(enum=["debit", "credit"]),
            "amount": money_schema(),
            "channel": string_schema(),
        },
        required=[
            "tx_id",
            "date",
            "merchant",
            "category",
            "direction",
            "amount",
        ],
    )
    category_item = object_schema(
        {
            "category": string_schema(),
            "count": integer_schema(minimum=1),
            "amount": money_schema(),
        },
        required=["category", "count", "amount"],
    )
    output_schema = object_schema(
        {
            "summary": string_schema(),
            "account": object_schema(
                {
                    "account_id": string_schema(),
                    "account_type": string_schema(),
                    "last4": string_schema(pattern=r"^\d{4}$"),
                },
                required=["account_id", "account_type", "last4"],
            ),
            "period": object_schema(
                {
                    "from_date": string_schema(format="date"),
                    "to_date": string_schema(format="date"),
                    "days": integer_schema(minimum=1),
                },
                required=["from_date", "to_date", "days"],
            ),
            "totals": object_schema(
                {
                    "count": integer_schema(minimum=0),
                    "debit_count": integer_schema(minimum=0),
                    "credit_count": integer_schema(minimum=0),
                    "total_debit": money_schema(),
                    "total_credit": money_schema(),
                    "net": money_schema(),
                },
                required=[
                    "count",
                    "debit_count",
                    "credit_count",
                    "total_debit",
                    "total_credit",
                    "net",
                ],
            ),
            "by_category": array_schema(category_item),
            "transactions": array_schema(transaction_item),
            "truncated": {"type": "boolean"},
            "as_of": string_schema(),
        },
        required=[
            "summary",
            "account",
            "period",
            "totals",
            "by_category",
            "transactions",
            "truncated",
            "as_of",
        ],
    )

    def handler(
        arguments: dict[str, Any], context: ToolCallContext
    ) -> dict[str, Any]:
        days = int(arguments.get("days", 90))
        limit = int(arguments.get("limit", 50))
        category = arguments.get("category") or None
        accounts = services.bank_access.resolve_accounts(
            context.user_id, arguments["account_ref"]
        )
        account = accounts[0]
        rows = services.bank_access.transactions(
            [account], days=days, category=category
        )
        debits = [row for row in rows if row["direction"] == "debit"]
        credits = [row for row in rows if row["direction"] == "credit"]
        total_debit = sum((row["amount"] for row in debits), Decimal("0.00"))
        total_credit = sum((row["amount"] for row in credits), Decimal("0.00"))

        category_totals: dict[str, dict[str, Any]] = {}
        for row in debits:
            bucket = category_totals.setdefault(
                row["category"], {"count": 0, "amount": Decimal("0.00")}
            )
            bucket["count"] += 1
            bucket["amount"] += row["amount"]
        by_category = [
            {
                "category": category_name,
                "count": bucket["count"],
                "amount": money_text(bucket["amount"]),
            }
            for category_name, bucket in sorted(
                category_totals.items(),
                key=lambda item: item[1]["amount"],
                reverse=True,
            )
        ]

        returned = rows[:limit]
        from_date = TODAY - timedelta(days=days)
        summary = (
            f"{account['type']}（尾号 {account['last4']}）近 {days} 天"
            f"共 {len(rows)} 笔交易，支出 ¥{total_debit:,.2f}，"
            f"收入 ¥{total_credit:,.2f}。"
        )
        return {
            "summary": summary,
            "account": {
                "account_id": account["account_id"],
                "account_type": account["type"],
                "last4": account["last4"],
            },
            "period": {
                "from_date": from_date.isoformat(),
                "to_date": TODAY.isoformat(),
                "days": days,
            },
            "totals": {
                "count": len(rows),
                "debit_count": len(debits),
                "credit_count": len(credits),
                "total_debit": money_text(total_debit),
                "total_credit": money_text(total_credit),
                "net": money_text(total_credit - total_debit),
            },
            "by_category": by_category,
            "transactions": [
                {
                    "tx_id": row["tx_id"],
                    "date": row["date"],
                    "merchant": row["merchant"],
                    "category": row["category"],
                    "direction": row["direction"],
                    "amount": money_text(row["amount"]),
                    "channel": row["channel"],
                }
                for row in returned
            ],
            "truncated": len(rows) > len(returned),
            "as_of": now_iso(),
        }

    return ToolDefinition(
        name="get_transactions",
        description=(
            "查询当前客户指定账户在给定天数内的流水，并汇总收入、支出与支出类别。"
            "最多返回 200 条，完整聚合统计不受返回条数截断影响。"
        ),
        category="accounts",
        handler=handler,
        input_schema=object_schema(
            {
                "account_ref": string_schema(
                    "账户别名、尾号或不透明账户 ID。",
                    min_length=1,
                    max_length=32,
                ),
                "days": integer_schema(
                    "查询最近 N 天，默认 90。",
                    minimum=1,
                    maximum=365,
                    default=90,
                ),
                "category": string_schema(
                    "可选类别精确过滤，例如 餐饮。",
                    max_length=20,
                ),
                "limit": integer_schema(
                    "最多返回多少条明细。",
                    minimum=1,
                    maximum=200,
                    default=50,
                ),
            },
            required=["account_ref"],
        ),
        output_schema=output_schema,
        mutating=False,
        risk_tier="R1",
        permissions=("transactions:read",),
        implementation_status="mocked",
        data_sources=(TRANSACTION_SOURCE, ACCOUNT_SOURCE),
        simulated=True,
        tags=("transactions", "spending", "read-only"),
    )
