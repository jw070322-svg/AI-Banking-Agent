"""organizer.py —— 数据整理 Agent 核心。

职责：把**契约场景**投影成各队友模块能直接读取的视图与条件。
它不是第四个转换器：

- 会话账本 → 契约场景：仍由 FirstAgent 的 `analysis_bridge.py` 负责；
- 环境生成内部格式 → 契约场景：仍由 `scenario_adapter.py` 负责；
- 本模块只做「契约场景 → 各模块视图」，只读、无状态、不写账本。

输出：
- analysis：契约场景 + 可用月份 / 缺失区块；
- recommendation：对齐 matching_core 的 profile + 金额条件；
- cards：卡片 / 信用卡账单 / 卡片事件；
- display：只读展示摘要；
- manifest：来源、版本、质量检查、假设与警告。

用法：
    python organizer.py --input fixtures/SCENARIO_F.json --out-dir organized
    python organizer.py --input fixtures/SCENARIO_G.json --context context.json
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from analysis import (
    budget_advice,
    load_scenario,
    monthly_report,
    normalize_scenario,
    overall_summary,
)
from analysis.data import available_months, parse_date

ORGANIZER_VERSION = "1.0.0"
SUPPORTED_SCHEMA_VERSION = "1.0.0"

# 契约场景正常不应包含这些字段；出现时先移除，再交给下游
PII_KEYS = {
    "id_number",
    "id_card",
    "phone",
    "mobile",
    "email",
    "address",
    "card_number",
    "account_number",
}

# 质量清单关注的共享区块
SHARED_BLOCKS = (
    "accounts",
    "transactions",
    "cards",
    "credit_card_bill",
    "subscriptions",
    "family",
    "calendar_events",
    "budget",
    "activity_calendar",
    "card_events",
)

DEFAULT_DAYS = 30
DEFAULT_HORIZON_DAYS = 30


class OrganizerError(ValueError):
    """整理输入不合法。"""


# ---------------------------------------------------------------------------
# 清洗与质量检查
# ---------------------------------------------------------------------------

def _strip_pii(value: Any, removed: List[str]) -> Any:
    """递归移除 PII 字段；只按字段名移除，不猜内容。"""
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            if key in PII_KEYS:
                removed.append(key)
                continue
            cleaned[key] = _strip_pii(item, removed)
        return cleaned
    if isinstance(value, list):
        return [_strip_pii(item, removed) for item in value]
    return value


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _booked_transactions(scenario: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        item for item in scenario.get("transactions", []) or []
        if isinstance(item, dict) and item.get("status") == "booked"
    ]


def _quality_report(scenario: Dict[str, Any], pii_removed: List[str]) -> Dict[str, Any]:
    transactions = [
        item for item in scenario.get("transactions", []) or []
        if isinstance(item, dict)
    ]
    booked = _booked_transactions(scenario)
    ids = [
        str(item.get("transaction_id"))
        for item in transactions
        if item.get("transaction_id")
    ]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})

    invalid_amounts = sum(
        1 for item in transactions
        if not _is_int(item.get("amount_minor"))
    )
    missing_categories = sorted({
        str(item.get("category"))
        for item in transactions
        if not item.get("category")
    })

    income_total = sum(
        item["amount_minor"] for item in booked
        if item.get("transaction_type") == "income"
        and _is_int(item.get("amount_minor"))
    )
    spending_total = sum(
        item["amount_minor"] for item in booked
        if item.get("transaction_type") in {"expense", "refund"}
        and _is_int(item.get("amount_minor"))
    )

    return {
        "transaction_count": len(transactions),
        "booked_count": len(booked),
        "duplicate_transaction_ids": duplicates,
        "invalid_amount_count": invalid_amounts,
        "missing_categories": missing_categories,
        "pii_fields_removed": sorted(set(pii_removed)),
        "income_total_minor": income_total,
        "spending_total_minor": spending_total,
        "has_income": income_total > 0,
        "has_spending": spending_total > 0,
        "low_spending": income_total > 0 and spending_total * 10 < income_total,
    }


def _missing_blocks(scenario: Dict[str, Any]) -> List[str]:
    return [name for name in SHARED_BLOCKS if not scenario.get(name)]


# ---------------------------------------------------------------------------
# 视图投影
# ---------------------------------------------------------------------------

def _analysis_view(
    scenario: Dict[str, Any],
    missing_blocks: List[str],
) -> Dict[str, Any]:
    months = available_months(scenario)
    return {
        "scenario": scenario,
        "available_months": months,
        "latest_month": months[-1] if months else None,
        "booked_transaction_count": len(_booked_transactions(scenario)),
        "missing_blocks": missing_blocks,
        "amount_unit": "minor",
        "notes": [
            "只统计 status=booked 的交易；金额为 CNY 整数分",
            "可直接传给 tools.call_tool / pipeline.run_pipeline",
        ],
    }


def _recommendation_view(
    scenario: Dict[str, Any],
    context: Dict[str, Any],
    advice: Dict[str, Any],
) -> Dict[str, Any]:
    warnings: List[str] = []
    assumptions: List[str] = []

    configured = context.get("configured_amount_minor")
    if configured is not None and (not _is_int(configured) or configured < 0):
        warnings.append("configured_amount_minor 无效，已忽略")
        configured = None

    headroom = advice["investment"]["headroom_minor"]
    if configured is None:
        budget_minor = headroom
        budget_source = "analysis_headroom"
        assumptions.append("未提供配置金额，可投金额取分析上限")
    elif headroom > 0:
        budget_minor = min(configured, headroom)
        budget_source = "min_configured_analysis"
    else:
        # 与 FirstAgent 当前推荐逻辑一致：分析上限为 0 时保留配置金额，
        # 但保留警告，不静默清空产品推荐。
        budget_minor = configured
        budget_source = "configured_analysis_zero"

    profile = context.get("profile")
    if not isinstance(profile, dict):
        profile = {}
    goal = context.get("goal")
    if not isinstance(goal, dict):
        goal = {}

    risk_tolerance = profile.get("risk_tolerance")
    if risk_tolerance is not None and (not _is_int(risk_tolerance) or risk_tolerance < 0):
        warnings.append("risk_tolerance 无效，按缺失处理")
        risk_tolerance = None
    if risk_tolerance is None:
        warnings.append("未提供风险档案，推荐模块将返回 needs_profile_completion")

    risk_capacity = profile.get("risk_capacity")
    if risk_capacity is None:
        risk_capacity = 1
        assumptions.append("未提供 risk_capacity，使用 1（与现有集成一致）")
    elif not _is_int(risk_capacity) or risk_capacity < 0:
        warnings.append("risk_capacity 无效，使用 1")
        risk_capacity = 1

    horizon_days = context.get("horizon_days")
    if not _is_int(horizon_days) or not 1 <= horizon_days <= 3650:
        months = goal.get("months")
        if _is_int(months) and 1 <= months <= 36:
            horizon_days = months * 30
            assumptions.append("horizon_days 未提供，按 goal.months × 30 计算")
        else:
            horizon_days = DEFAULT_HORIZON_DAYS
            assumptions.append("horizon_days 未提供或 goal.months 无效，默认 30 天")
            if months is not None:
                warnings.append("goal.months 必须是 1~36 的整数，已忽略")

    max_redemption_days = profile.get("max_redemption_days", 1)
    if not _is_int(max_redemption_days) or max_redemption_days < 0:
        max_redemption_days = 1
        warnings.append("max_redemption_days 无效，使用 1")

    objective = profile.get("objective") or "liquidity"
    preferred_categories = profile.get("preferred_categories")
    if not isinstance(preferred_categories, list):
        preferred_categories = ["cash"]

    user = scenario.get("user") if isinstance(scenario.get("user"), dict) else {}
    user_id = profile.get("user_id") or user.get("user_id")

    return {
        "money_unit": "budget_cny is CNY yuan; conditions amounts are CNY minor",
        "profile": {
            "user_id": user_id,
            "risk_tolerance": risk_tolerance,
            "risk_capacity": risk_capacity,
            "budget_cny": round(budget_minor / 100, 2),
            "horizon_days": horizon_days,
            "max_redemption_days": max_redemption_days,
            "objective": objective,
            "preferred_categories": preferred_categories,
        },
        "conditions": {
            "budget_minor": budget_minor,
            "budget_source": budget_source,
            "configured_amount_minor": configured,
            "analysis_headroom_minor": headroom,
            "monthly_surplus_minor": advice["monthly_surplus_minor"],
            "lowest_balance_minor": advice["lowest_balance_minor"],
            "shortfall_days": advice["shortfall_days"],
            "goal": goal or None,
            "consent": context.get("consent"),
            "budget_policy": advice["policy"],
        },
        "warnings": warnings,
        "assumptions": assumptions,
    }


def _cards_view(scenario: Dict[str, Any]) -> Dict[str, Any]:
    cards = scenario.get("cards") or []
    bill = scenario.get("credit_card_bill")
    events = scenario.get("card_events") or []
    missing = [
        name for name, value in (
            ("cards", cards),
            ("credit_card_bill", bill),
            ("card_events", events),
        )
        if not value
    ]
    return {
        "available": bool(cards or bill or events),
        "amount_unit": "minor",
        "cards": cards,
        "credit_card_bill": bill,
        "card_events": events,
        "missing": missing,
    }


def _display_view(scenario: Dict[str, Any]) -> Dict[str, Any]:
    months = available_months(scenario)
    month = months[-1] if months else None
    report = monthly_report(scenario, month) if month else overall_summary(scenario)
    subscriptions = scenario.get("subscriptions") or []
    balance = sum(
        account.get("balance_minor", 0)
        for account in scenario.get("accounts", []) or []
        if isinstance(account, dict) and _is_int(account.get("balance_minor"))
    )
    return {
        "read_only": True,
        "ledger_modified": False,
        "amount_unit": "minor",
        "currency": scenario.get("currency", "CNY"),
        "month": month,
        "available_balance_minor": balance,
        "income_minor": report.get("income_minor", 0),
        "spending_minor": report.get("spending_minor", 0),
        "net_minor": report.get("net_minor", 0),
        "transaction_count": report.get("transaction_count", 0),
        "active_subscriptions": sum(
            1 for item in subscriptions
            if isinstance(item, dict) and item.get("status") == "active"
        ),
        "card_count": len(scenario.get("cards") or []),
        "note": "派生只读摘要，不是账本快照；实时会话请读 /api/snapshot",
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def _parse_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if context is None:
        context = {}
    if not isinstance(context, dict):
        raise OrganizerError("context 必须是 JSON 对象")
    result = dict(context)
    days = result.get("days", DEFAULT_DAYS)
    if not _is_int(days) or not 1 <= days <= 366:
        raise OrganizerError("context.days 必须是 1~366 的整数")
    result["days"] = days
    today = result.get("today")
    if isinstance(today, str):
        parsed = parse_date(today)
        if parsed is None:
            raise OrganizerError("context.today 必须是 YYYY-MM-DD")
        result["today"] = parsed
    elif today is not None and not hasattr(today, "isoformat"):
        raise OrganizerError("context.today 必须是日期或 YYYY-MM-DD")
    include_evaluation = result.get("include_evaluation", False)
    if not isinstance(include_evaluation, bool):
        raise OrganizerError("context.include_evaluation 必须是布尔值")
    result["include_evaluation"] = include_evaluation
    return result


def organize(
    scenario: Any,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把契约场景整理成多视图数据包。

    `scenario` 必须是契约场景（或可被 normalize_scenario 识别的格式）。
    会话状态请先在 FirstAgent 侧转成契约场景，不要在这里传原始账本。
    """
    ctx = _parse_context(context)
    canonical = copy.deepcopy(normalize_scenario(scenario))

    pii_removed: List[str] = []
    canonical = _strip_pii(canonical, pii_removed)

    if not ctx["include_evaluation"]:
        canonical.pop("expected_insights", None)
        canonical.pop("evaluation_only_fields", None)

    if canonical.get("ledger_modified") is True:
        raise OrganizerError("输入场景标记为可写，数据整理只接受只读场景")

    missing_blocks = _missing_blocks(canonical)
    quality = _quality_report(canonical, pii_removed)

    advice = budget_advice(
        canonical,
        days=ctx["days"],
        today=ctx.get("today"),
    )
    recommendation = _recommendation_view(canonical, ctx, advice)

    warnings: List[str] = []
    for message in list(advice.get("warnings", [])) + recommendation["warnings"]:
        if message not in warnings:
            warnings.append(message)
    if pii_removed:
        warnings.append(
            "已移除 PII 字段：" + "、".join(sorted(set(pii_removed)))
        )
    if not ctx["include_evaluation"]:
        warnings.append("expected_insights 已按对客规则移除")

    assumptions: List[str] = list(recommendation["assumptions"])
    assumptions.extend([
        "analysis 视图与契约场景同义，金额为整数分",
        "recommendation 视图的 budget_cny 为 CNY 元，其余金额为整数分",
        "display 视图是派生只读摘要，不是账本快照",
    ])

    views = {
        "analysis": _analysis_view(canonical, missing_blocks),
        "recommendation": recommendation,
        "cards": _cards_view(canonical),
        "display": _display_view(canonical),
    }

    return {
        "organizer_version": ORGANIZER_VERSION,
        "contract_schema_version": (
            canonical.get("schema_version") or SUPPORTED_SCHEMA_VERSION
        ),
        "source": ctx.get("source") or "contract_scenario",
        "views": views,
        "manifest": {
            "currency": canonical.get("currency", "CNY"),
            "amount_unit": "minor",
            "available_views": list(views),
            "view_status": {
                "analysis": "available",
                "recommendation": "available",
                "cards": "available" if views["cards"]["available"] else "empty",
                "display": "available",
            },
            "missing_blocks": missing_blocks,
            "quality": quality,
            "evaluation_fields_included": ctx["include_evaluation"],
            "assumptions": assumptions,
            "warnings": warnings,
            "ledger_modified": False,
            "simulated": True,
        },
    }


# ---------------------------------------------------------------------------
# 文件输出
# ---------------------------------------------------------------------------

def write_package(package: Dict[str, Any], out_dir: str | Path) -> List[Path]:
    """把数据包拆成队友可直接读取的独立 JSON 文件。"""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    views = package["views"]
    files = {
        "package.json": package,
        "analysis.scenario.json": views["analysis"],
        "recommendation.profile.json": views["recommendation"],
        "cards.view.json": views["cards"],
        "display.view.json": views["display"],
        "manifest.json": package["manifest"],
    }
    paths: List[Path] = []
    for name, payload in files.items():
        path = target / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="数据整理 Agent：契约场景 → 多模块视图")
    parser.add_argument("--input", required=True, help="契约场景 JSON")
    parser.add_argument("--context", help="上下文 JSON（profile/goal/金额/consent）")
    parser.add_argument("--out-dir", default="organized", help="输出目录")
    parser.add_argument("--print", action="store_true", help="同时打印完整数据包")
    args = parser.parse_args(argv)

    try:
        scenario = load_scenario(args.input)
        context = None
        if args.context:
            context = json.loads(Path(args.context).read_text(encoding="utf-8"))
        package = organize(scenario, context)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"整理失败：{exc}")
        return 1

    paths = write_package(package, args.out_dir)
    manifest = package["manifest"]
    print(f"整理完成：{package['source']} → {args.out_dir}")
    print(f"视图：{' / '.join(manifest['available_views'])}")
    print(f"缺失区块：{', '.join(manifest['missing_blocks']) or '无'}")
    print(
        f"交易：{manifest['quality']['transaction_count']} 笔，"
        f"booked {manifest['quality']['booked_count']} 笔"
    )
    for warning in manifest["warnings"]:
        print(f"[警告] {warning}")
    print("文件：")
    for path in paths:
        print(f"  {path}")
    if args.print:
        print(json.dumps(package, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
