"""pipeline.py —— 环境生成 → 分析内核的端到端流水线。

一次调用完成：
1. （可选）调用环境生成 Agent 产出契约场景；
2. 生成当月账单报告（分类统计、商户排行、信用卡）；
3. 识别异常与提醒；
4. 计算订阅负担；
5. 投影未来 N 天现金流；
6. 计算锁定预算后的可用流动性；
7. 给出每月可安全储蓄/投资的建议金额；
8. （可选）用 expected_insights 评估识别效果。

输出是纯 JSON 可序列化字典，金额全部为 CNY 整数分，`ledger_modified` 恒为 false。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from analysis import (
    available_liquidity,
    budget_advice,
    detect_anomalies,
    evaluate_detection,
    monthly_report,
    overall_summary,
    project_cashflow,
    subscription_burden,
)
from analysis.data import available_months
from bridge import BridgeError, generate_scenario

SCHEMA_VERSION = "1.0.0"


def _dedupe(messages: List[str]) -> List[str]:
    seen = set()
    result = []
    for message in messages:
        if message not in seen:
            seen.add(message)
            result.append(message)
    return result


def run_pipeline(
    *,
    prompt: Optional[str] = None,
    scenario: Optional[Dict[str, Any]] = None,
    scenario_type: Optional[str] = None,
    seed: Optional[int] = None,
    reference_date: Optional[str] = None,
    days: int = 30,
    month: Optional[str] = None,
    today: Optional[date] = None,
    include_evaluation: bool = False,
) -> Dict[str, Any]:
    """执行完整分析链路。

    参数二选一：
    - prompt：交给环境生成 Agent 生成新场景；
    - scenario：直接传入契约场景（来自会话账本或 fixtures）。
    """
    if scenario is None:
        if not prompt:
            raise BridgeError("INVALID_ARGUMENT", "必须提供 prompt 或 scenario")
        scenario = generate_scenario(
            prompt,
            scenario_type=scenario_type,
            seed=seed,
            reference_date=reference_date,
        )

    months = available_months(scenario)
    report_month = month or (months[-1] if months else None)

    report = (
        monthly_report(scenario, report_month)
        if report_month
        else overall_summary(scenario)
    )
    findings = detect_anomalies(scenario, today=today)
    burden = subscription_burden(scenario, today=today)
    projection = project_cashflow(scenario, days=days, today=today)
    liquidity = available_liquidity(
        scenario, days=days, today=today, projection=projection
    )
    budget = budget_advice(
        scenario,
        days=days,
        month=report_month,
        today=today,
        projection=projection,
    )

    warnings = _dedupe(
        list(projection.get("warnings", []))
        + list(liquidity.get("warnings", []))
        + list(budget.get("warnings", []))
    )

    result: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "succeeded",
        "simulated": True,
        "ledger_modified": False,
        "scenario": {
            "scenario_id": scenario.get("scenario_id"),
            "scenario_type": scenario.get("scenario_type"),
            "scenario_name": scenario.get("scenario_name"),
            "created_at": scenario.get("created_at"),
            "currency": scenario.get("currency", "CNY"),
            "transaction_count": len(scenario.get("transactions", [])),
            "card_count": len(scenario.get("cards", []) or []),
            "calendar_event_count": len(scenario.get("calendar_events", []) or []),
        },
        "period": {
            "month": report_month,
            "as_of": projection["as_of"],
            "horizon_days": days,
        },
        "summary": {
            "income_minor": report.get("income_minor", 0),
            "spending_minor": report.get("spending_minor", 0),
            "net_minor": report.get("net_minor", 0),
            "lowest_balance_minor": liquidity["minimum_balance_minor"],
            "safe_to_spend_now_minor": liquidity["safe_to_spend_now_minor"],
            "safe_to_save_monthly_minor": budget["savings"]["safe_monthly_minor"],
            "safe_to_invest_monthly_minor": budget["investment"]["safe_monthly_minor"],
            "active_subscriptions": burden["active_count"],
            "finding_count": len(findings),
        },
        "report": report,
        "findings": findings,
        "subscription_burden": burden,
        "cashflow": projection,
        "liquidity": {key: value for key, value in liquidity.items() if key != "projection"},
        "budget_advice": budget,
        "warnings": warnings,
        "error": None,
    }

    # 标准答案只在评测模式下返回，避免对客回答"抄答案"
    if include_evaluation and scenario.get("expected_insights"):
        result["evaluation"] = evaluate_detection(scenario)

    return result


def format_summary(result: Dict[str, Any]) -> str:
    """把流水线结果压成一段中文摘要，方便主 Agent 直接引用。"""
    summary = result["summary"]
    period = result.get("period", {})
    parts = [
        f"场景 {result['scenario'].get('scenario_type')}，",
        f"统计月份 {period.get('month') or '全部'}：",
        f"收入 {summary['income_minor'] / 100:.2f} 元，",
        f"消费 {summary['spending_minor'] / 100:.2f} 元，",
        f"识别到 {summary['finding_count']} 条提醒，",
        f"未来 {period.get('horizon_days')} 天最低余额 "
        f"{summary['lowest_balance_minor'] / 100:.2f} 元。",
    ]
    if result.get("warnings"):
        parts.append("注意：" + "；".join(result["warnings"]))
    return "".join(parts)
