"""Sensitive transaction execution boundary.

The only implementation supplied here is a mock gateway. The registry must also
have verified Risk Engine and Compliance Guard adapters before this handler is
reachable, and must obtain explicit confirmation plus a stable idempotency key.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..errors import TRANSACTION_GATEWAY_UNAVAILABLE, ToolLayerError
from ..models import ToolCallContext, ToolDefinition
from ..schema import boolean_schema, money_schema, object_schema, string_schema
from ..services import ToolServices, TransactionRequest
from ..utils import now_iso, money_text


def register(registry: Any, services: ToolServices) -> None:
    registry.register(_definition(services))


def _definition(services: ToolServices) -> ToolDefinition:
    output_schema = object_schema(
        {
            "summary": string_schema(),
            "transaction_id": string_schema(),
            "status": string_schema(enum=["simulated_completed"]),
            "simulated": boolean_schema(),
            "duplicate": boolean_schema(),
            "from_account": object_schema(
                {
                    "account_id": string_schema(),
                    "account_type": string_schema(),
                    "last4": string_schema(pattern=r"^\d{4}$"),
                },
                required=["account_id", "account_type", "last4"],
            ),
            "beneficiary": object_schema(
                {
                    "name": string_schema(),
                    "bank": string_schema(),
                    "account_last4": string_schema(pattern=r"^\d{4}$"),
                },
                required=["name", "bank", "account_last4"],
            ),
            "amount": money_schema(),
            "currency": string_schema(),
            "fee": money_schema(),
            "balance_before": money_schema(),
            "balance_after": money_schema(),
            "executed_at": string_schema(),
            "note": string_schema(),
            "disclaimer": string_schema(),
            "as_of": string_schema(),
        },
        required=[
            "summary",
            "transaction_id",
            "status",
            "simulated",
            "duplicate",
            "from_account",
            "beneficiary",
            "amount",
            "currency",
            "fee",
            "balance_before",
            "balance_after",
            "executed_at",
            "note",
            "disclaimer",
            "as_of",
        ],
    )

    def handler(
        arguments: dict[str, Any], context: ToolCallContext
    ) -> dict[str, Any]:
        gateway = services.transaction_gateway
        if gateway is None or not gateway.is_connected:
            raise ToolLayerError(
                TRANSACTION_GATEWAY_UNAVAILABLE,
                "交易网关未接通；拒绝执行，且不会创建模拟回执。",
            )
        if not getattr(gateway, "simulated", False):
            raise ToolLayerError(
                TRANSACTION_GATEWAY_UNAVAILABLE,
                "原型未获准连接真实交易网关；已拒绝执行。",
            )
        if not context.idempotency_key:
            # Registry enforces this too; keep a local fail-safe.
            raise ToolLayerError(
                "IDEMPOTENCY_KEY_REQUIRED",
                "敏感交易缺少幂等键，拒绝执行。",
            )
        if not context.confirmed or not context.confirmation_id:
            raise ToolLayerError(
                "CONFIRMATION_REQUIRED",
                "敏感交易缺少用户确认，拒绝执行。",
            )
        request = TransactionRequest(
            user_id=context.user_id,
            session_id=context.session_id,
            from_account_ref=arguments["from_account_ref"],
            beneficiary_name=arguments["beneficiary_name"],
            amount=str(arguments["amount"]),
            currency=str(arguments.get("currency", "CNY")),
            idempotency_key=context.idempotency_key,
            confirmation_id=context.confirmation_id,
            note=str(arguments.get("note", "") or ""),
        )
        receipt = gateway.execute(request)
        duplicate = bool(receipt.get("duplicate"))
        summary = (
            "幂等重放：返回同一笔模拟转账结果，资金未再次变动。"
            if duplicate
            else (
                f"模拟转账完成：向 {receipt['beneficiary']['name']} "
                f"（尾号 {receipt['beneficiary']['account_last4']}）转账 "
                f"¥{Decimal(receipt['amount']):,.2f}；"
                "这是模拟交易，不会产生真实资金变动。"
            )
        )
        return {
            "summary": summary,
            "transaction_id": receipt["transfer_id"],
            "status": "simulated_completed",
            "simulated": True,
            "duplicate": duplicate,
            "from_account": {
                "account_id": receipt["from_account_id"],
                "account_type": receipt["from_account_type"],
                "last4": receipt["from_account_last4"],
            },
            "beneficiary": {
                "name": receipt["beneficiary"]["name"],
                "bank": receipt["beneficiary"]["bank"],
                "account_last4": receipt["beneficiary"]["account_last4"],
            },
            "amount": money_text(receipt["amount"]),
            "currency": receipt["currency"],
            "fee": money_text(receipt["fee"]),
            "balance_before": money_text(receipt["balance_before"]),
            "balance_after": money_text(receipt["balance_after"]),
            "executed_at": receipt["executed_at"],
            "note": str(receipt.get("note") or ""),
            "disclaimer": (
                "原型定义：禁止真实资金交易。该回执仅证明内存模拟账本发生变化，"
                "不能作为真实付款凭证。"
            ),
            "as_of": now_iso(),
        }

    return ToolDefinition(
        name="execute_transaction",
        description=(
            "高敏感模拟转账。默认失败关闭：必须注入已验证的 Risk Engine 与 "
            "Compliance Guard 适配器、明确确认和幂等键，并且只能使用模拟交易网关。"
            "原型绝不执行真实交易。"
        ),
        category="transactions",
        handler=handler,
        input_schema=object_schema(
            {
                "from_account_ref": string_schema(
                    "转出账户别名/尾号/不透明 ID。",
                    min_length=1,
                    max_length=32,
                ),
                "beneficiary_name": string_schema(
                    "收款人姓名，必须已在当前客户名册中。",
                    min_length=1,
                    max_length=40,
                ),
                "amount": money_schema("转账金额，CNY。"),
                "currency": string_schema(
                    "币种；本原型仅支持 CNY。",
                    enum=["CNY"],
                    default="CNY",
                ),
                "note": string_schema(
                    "可选转账备注。",
                    max_length=140,
                ),
            },
            required=["from_account_ref", "beneficiary_name", "amount"],
        ),
        output_schema=output_schema,
        mutating=True,
        risk_tier="R4",
        permissions=("transfer:write",),
        requires_confirmation=True,
        requires_safety_checks=True,
        implementation_status="awaiting_integration",
        data_sources=(
            "MockBank transfer handler (simulation only)",
            "Verified Risk Engine adapter (required, not connected by default)",
            "Verified Compliance Guard adapter (required, not connected by default)",
        ),
        simulated=True,
        max_attempts=1,
        tags=(
            "transaction",
            "sensitive-write",
            "fail-closed",
            "simulation-only",
        ),
    )
