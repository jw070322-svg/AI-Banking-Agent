"""Mock product discovery and comparison tools."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..errors import PRODUCT_NOT_FOUND, PRODUCT_TYPE_MISMATCH, ToolLayerError
from ..models import ToolCallContext, ToolDefinition
from ..schema import (
    array_schema,
    integer_schema,
    money_schema,
    object_schema,
    string_schema,
)
from ..services import ToolServices
from ..utils import now_iso, percent_text


PRODUCT_SOURCE = "MockBank simulated product catalogue v1"
PRODUCT_TYPES = (
    "savings",
    "time_deposit",
    "loan",
    "credit_card",
    "fund",
)


def register(registry: Any, services: ToolServices) -> None:
    registry.register(_search_definition(services))
    registry.register(_compare_definition(services))


def _product_schema() -> dict[str, Any]:
    return object_schema(
        {
            "product_id": string_schema(),
            "name": string_schema(),
            "product_type": string_schema(enum=list(PRODUCT_TYPES)),
            "provider": string_schema(),
            "currency": string_schema(),
            "indicative_rate_percent": string_schema(format="decimal"),
            "rate_basis": string_schema(),
            "annual_fee": money_schema(),
            "minimum_amount": money_schema(),
            "term_months": integer_schema(nullable=True),
            "risk_level": string_schema(enum=["R1", "R2", "R3", "R4"]),
            "liquidity": string_schema(
                enum=["high", "medium", "low", "not_applicable"]
            ),
            "features": array_schema(string_schema()),
            "eligibility": string_schema(),
            "tags": array_schema(string_schema()),
            "source_updated_at": string_schema(format="date"),
        },
        required=[
            "product_id",
            "name",
            "product_type",
            "provider",
            "currency",
            "indicative_rate_percent",
            "rate_basis",
            "annual_fee",
            "minimum_amount",
            "risk_level",
            "liquidity",
            "features",
            "eligibility",
            "source_updated_at",
        ],
    )


def _search_definition(services: ToolServices) -> ToolDefinition:
    output_schema = object_schema(
        {
            "summary": string_schema(),
            "count": integer_schema(minimum=0),
            "results": array_schema(_product_schema()),
            "filters": object_schema(
                {
                    "product_type": string_schema(nullable=True),
                    "query": string_schema(nullable=True),
                },
                required=["product_type", "query"],
            ),
            "disclaimer": string_schema(),
            "as_of": string_schema(),
        },
        required=[
            "summary",
            "count",
            "results",
            "filters",
            "disclaimer",
            "as_of",
        ],
    )

    def handler(
        arguments: dict[str, Any], context: ToolCallContext
    ) -> dict[str, Any]:
        product_type = arguments.get("product_type") or None
        query = arguments.get("query") or None
        results = services.products.search(
            product_type=product_type,
            query=query,
            max_results=int(arguments.get("max_results", 5)),
        )
        if results:
            summary = (
                f"在模拟产品目录中找到 {len(results)} 个匹配产品；"
                "利率/收益率为目录示例，不构成推荐。"
            )
        else:
            summary = (
                "模拟产品目录中没有找到符合条件的产品。"
                "未使用外部数据，也未推断不存在的产品。"
            )
        return {
            "summary": summary,
            "count": len(results),
            "results": results,
            "filters": {
                "product_type": product_type,
                "query": query,
            },
            "disclaimer": (
                "产品目录为 MockBank 模拟数据；指示利率、收益率、费用和额度"
                "不代表真实报价，不构成投资或信贷建议。"
            ),
            "as_of": now_iso(),
        }

    return ToolDefinition(
        name="search_products",
        description=(
            "在明确标注为模拟的产品目录中按类型和关键词检索存款、贷款、信用卡和基金产品。"
            "返回目录事实与来源日期，不虚构产品，也不做适当性判断。"
        ),
        category="products",
        handler=handler,
        input_schema=object_schema(
            {
                "product_type": string_schema(
                    "可选产品类型过滤。",
                    enum=list(PRODUCT_TYPES),
                ),
                "query": string_schema(
                    "可选关键词，例如“稳健”“房贷”。",
                    max_length=100,
                ),
                "max_results": integer_schema(
                    "最多返回条数，默认 5。",
                    minimum=1,
                    maximum=20,
                    default=5,
                ),
            },
            required=[],
        ),
        output_schema=output_schema,
        mutating=False,
        risk_tier="R2",
        permissions=("products:read",),
        implementation_status="mocked",
        data_sources=(PRODUCT_SOURCE,),
        simulated=True,
        tags=("products", "search", "mock-catalog", "read-only"),
    )


def _compare_definition(services: ToolServices) -> ToolDefinition:
    value_schema = object_schema(
        {
            "product_id": string_schema(),
            "value": string_schema(),
        },
        required=["product_id", "value"],
    )
    attribute_schema = object_schema(
        {
            "attribute": string_schema(),
            "label": string_schema(),
            "values": array_schema(value_schema, min_items=2, max_items=4),
        },
        required=["attribute", "label", "values"],
    )
    output_schema = object_schema(
        {
            "summary": string_schema(),
            "product_type": string_schema(enum=list(PRODUCT_TYPES)),
            "products": array_schema(_product_schema(), min_items=2, max_items=4),
            "attributes": array_schema(attribute_schema),
            "observations": array_schema(string_schema()),
            "disclaimer": string_schema(),
            "as_of": string_schema(),
        },
        required=[
            "summary",
            "product_type",
            "products",
            "attributes",
            "observations",
            "disclaimer",
            "as_of",
        ],
    )

    def handler(
        arguments: dict[str, Any], context: ToolCallContext
    ) -> dict[str, Any]:
        product_ids = list(arguments["product_ids"])
        if len(set(product_ids)) != len(product_ids):
            raise ToolLayerError(
                "INVALID_ARGUMENTS", "product_ids 不能重复。"
            )
        products = []
        for product_id in product_ids:
            item = services.products.get(product_id)
            if item is None:
                raise ToolLayerError(
                    PRODUCT_NOT_FOUND,
                    f"模拟产品目录中未找到产品「{product_id}」。",
                    details={"product_id": product_id},
                )
            products.append(item)
        product_types = {item["product_type"] for item in products}
        if len(product_types) != 1:
            raise ToolLayerError(
                PRODUCT_TYPE_MISMATCH,
                "仅支持比较同一产品类型；跨类型利率和费用口径不同，不能直接比较。",
            )

        attributes = [
            _attribute(
                "indicative_rate_percent",
                "指示性年化利率/收益率 (%)",
                products,
                lambda item: item["indicative_rate_percent"],
            ),
            _attribute(
                "annual_fee",
                "年费/账户管理费 (CNY)",
                products,
                lambda item: item["annual_fee"],
            ),
            _attribute(
                "minimum_amount",
                "最低金额/额度 (CNY)",
                products,
                lambda item: item["minimum_amount"],
            ),
            _attribute(
                "term_months",
                "示例期限 (月)",
                products,
                lambda item: (
                    str(item["term_months"])
                    if item["term_months"] is not None
                    else "不适用"
                ),
            ),
            _attribute(
                "risk_level",
                "风险等级",
                products,
                lambda item: item["risk_level"],
            ),
            _attribute(
                "liquidity",
                "流动性",
                products,
                lambda item: item["liquidity"],
            ),
            _attribute(
                "features",
                "主要特点",
                products,
                lambda item: "；".join(item["features"]),
            ),
        ]

        product_type = products[0]["product_type"]
        observations = []
        if product_type == "loan":
            best_rate = min(
                products, key=lambda item: Decimal(item["indicative_rate_percent"])
            )
            observations.append(
                f"{best_rate['product_id']} 的指示性利率最低；"
                "借款成本还受期限、费用和实际审批影响，这不是推荐。"
            )
        else:
            best_rate = max(
                products, key=lambda item: Decimal(item["indicative_rate_percent"])
            )
            observations.append(
                f"{best_rate['product_id']} 的指示性年化率最高；"
                "更高的展示收益通常伴随更高风险，这不是推荐。"
            )
        lowest_fee = min(products, key=lambda item: Decimal(item["annual_fee"]))
        observations.append(
            f"{lowest_fee['product_id']} 的年费/账户管理费最低。"
        )
        observations.append(
            "比较仅覆盖目录字段，未纳入适当性、流动性需求、税费或真实合同条款。"
        )
        return {
            "summary": (
                f"已对 {len(products)} 个同为 {product_type} 的模拟产品做字段对比；"
                "结论仅为事实观察，不构成推荐。"
            ),
            "product_type": product_type,
            "products": products,
            "attributes": attributes,
            "observations": observations,
            "disclaimer": (
                "产品与利率均为模拟目录数据；跨产品适当性和真实报价需由正式系统确认。"
            ),
            "as_of": now_iso(),
        }

    return ToolDefinition(
        name="compare_products",
        description=(
            "比较 2-4 个同类型模拟产品，输出逐字段并列、最低/最高指示性利率与费用观察。"
            "跨类型比较会被拒绝；结果不是推荐或适当性结论。"
        ),
        category="products",
        handler=handler,
        input_schema=object_schema(
            {
                "product_ids": array_schema(
                    string_schema(
                        "模拟产品 ID。",
                        min_length=1,
                        max_length=40,
                    ),
                    min_items=2,
                    max_items=4,
                    unique_items=True,
                )
            },
            required=["product_ids"],
        ),
        output_schema=output_schema,
        mutating=False,
        risk_tier="R2",
        permissions=("products:read",),
        implementation_status="mocked",
        data_sources=(PRODUCT_SOURCE,),
        simulated=True,
        tags=("products", "compare", "mock-catalog", "read-only"),
    )


def _attribute(
    name: str,
    label: str,
    products: list[dict[str, Any]],
    getter: Any,
) -> dict[str, Any]:
    return {
        "attribute": name,
        "label": label,
        "values": [
            {
                "product_id": product["product_id"],
                "value": str(getter(product)),
            }
            for product in products
        ],
    }
