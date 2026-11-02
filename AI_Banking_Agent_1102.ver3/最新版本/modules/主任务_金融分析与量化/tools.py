"""tools.py —— 暴露给主 Agent 的分析工具。

主 Agent（王语嫣负责的 service/server）只需要：
    from tools import list_tools, call_tool
    result = call_tool("anomalies.detect", {}, data=session_scenario)

设计原则：
- 只读：不写账本、不发起交易，所有结果 `ledger_modified=false`；
- 纯 JSON：金额整数分，没有 datetime / Decimal / 自定义对象；
- 不抛异常：参数错误、上下文缺失都以 `status=rejected` 返回；
- 不返回标准答案：`expected_insights` 只在评测工具显式开启时使用。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from analysis import (
    annual_report,
    available_liquidity,
    budget_advice,
    category_breakdown,
    detect_anomalies,
    monthly_report,
    overall_summary,
    project_cashflow,
    subscription_burden,
)
from bridge import BridgeError, generate_scenario
from pipeline import run_pipeline

MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")

TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "scenario.generate",
        "description": (
            "调用环境生成 Agent 生成一份虚构场景（A~G），返回契约格式数据。"
            "默认剔除评测标准答案 expected_insights。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "自然语言需求，1~2000 字"},
                "scenario_type": {"type": "string", "enum": list("ABCDEFG")},
                "seed": {"type": "integer", "description": "可复现随机种子"},
                "reference_date": {"type": "string", "description": "YYYY-MM-DD"},
                "include_evaluation": {
                    "type": "boolean",
                    "description": "仅评测时开启，会在场景中保留 expected_insights",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "bills.summary",
        "description": "生成月度/年度/整体账单报告，包含分类、商户排行、信用卡账单。",
        "parameters": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "YYYY-MM，默认取数据中最新月份"},
                "year": {"type": "integer", "description": "年度报告"},
            },
        },
    },
    {
        "name": "bills.categories",
        "description": "按消费类别汇总，可按月或按年过滤。",
        "parameters": {
            "type": "object",
            "properties": {
                "month": {"type": "string"},
                "year": {"type": "integer"},
            },
        },
    },
    {
        "name": "anomalies.detect",
        "description": "识别重复扣款、失败转账、还款、续费、调价、生日、预算锁定、异常大额消费。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "subscriptions.burden",
        "description": "计算订阅月均支出、占工资比例、负担等级与即将扣费。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "cashflow.project",
        "description": "投影未来 N 天余额，含工资、信用卡还款、订阅续费、生日活动。",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 366},
            },
        },
    },
    {
        "name": "liquidity.available",
        "description": "计算锁定生日预算后的可用流动性以及锁定预算被挤占的风险。",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 366},
            },
        },
    },
    {
        "name": "budget.advice",
        "description": "按月度结余和现金流最低余额，给出每月可安全储蓄/投资的金额及约束。",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 366},
                "month": {"type": "string", "description": "YYYY-MM，默认最新月份"},
            },
        },
    },
    {
        "name": "analysis.pipeline",
        "description": "一次返回账单报告、异常、订阅负担、现金流、流动性与预算建议的完整分析。",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 366},
                "month": {"type": "string"},
                "include_evaluation": {
                    "type": "boolean",
                    "description": "仅评测时开启，会返回 expected_insights 对比结果",
                },
            },
        },
    },
]

_TOOL_NAMES = {spec["name"] for spec in TOOL_SPECS}


class ToolArgumentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def list_tools() -> List[Dict[str, Any]]:
    """返回工具清单（深拷贝，避免调用方改到全局配置）。"""
    return copy.deepcopy(TOOL_SPECS)


def _envelope(tool: str, status: str, data: Any = None, error: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return {
        "tool": tool,
        "status": status,
        "data": data,
        "error": error,
        "simulated": True,
        "ledger_modified": False,
    }


def _reject(tool: str, code: str, message: str) -> Dict[str, Any]:
    return _envelope(tool, "rejected", error={"code": code, "message": message})


def _validate_days(arguments: Dict[str, Any]) -> int:
    days = arguments.get("days", 30)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 366:
        raise ToolArgumentError("INVALID_ARGUMENT", "days 必须是 1~366 的整数")
    return days


def _validate_month(arguments: Dict[str, Any]) -> Optional[str]:
    month = arguments.get("month")
    if month is None:
        return None
    if not isinstance(month, str) or not MONTH_PATTERN.fullmatch(month):
        raise ToolArgumentError("INVALID_ARGUMENT", "month 必须是 YYYY-MM")
    return month


def _validate_year(arguments: Dict[str, Any]) -> Optional[int]:
    year = arguments.get("year")
    if year is None:
        return None
    if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2200:
        raise ToolArgumentError("INVALID_ARGUMENT", "year 必须是 1900~2200 的整数")
    return year


def _validate_bool(arguments: Dict[str, Any], key: str, default: bool = False) -> bool:
    value = arguments.get(key, default)
    if not isinstance(value, bool):
        raise ToolArgumentError("INVALID_ARGUMENT", f"{key} 必须是布尔值")
    return value


def _client_scenario(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """返回对客场景副本，去掉只给评测用的标准答案。

    只做浅拷贝：不改动环境生成侧幂等缓存里的原对象，也不深改嵌套数据。
    """
    safe = dict(scenario)
    safe.pop("expected_insights", None)
    safe.pop("evaluation_only_fields", None)
    return safe


def _resolve_scenario(arguments: Dict[str, Any], data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """工具上下文：优先用调用方传入的会话数据，其次读 scenario_file。"""
    if isinstance(data, dict):
        return data
    scenario_file = arguments.get("scenario_file")
    if scenario_file:
        from analysis import load_scenario
        try:
            return load_scenario(Path(scenario_file))
        except (OSError, ValueError) as exc:
            raise ToolArgumentError("SCENARIO_NOT_FOUND", f"无法读取场景文件：{exc}") from exc
    raise ToolArgumentError("MISSING_CONTEXT", "缺少会话场景数据（data 或 scenario_file）")


def _normalize_arguments(name: str, arguments: Any) -> Dict[str, Any]:
    if arguments is None:
        return {}
    if not isinstance(arguments, dict):
        raise ToolArgumentError("INVALID_ARGUMENT", "arguments 必须是 JSON 对象")
    spec = next((item for item in TOOL_SPECS if item["name"] == name), None)
    allowed = set(spec["parameters"].get("properties", {})) if spec else set()
    allowed.add("scenario_file")  # 本地调试用，不属于业务参数
    unknown = set(arguments) - allowed
    if unknown:
        raise ToolArgumentError("INVALID_ARGUMENT", f"不支持的参数：{', '.join(sorted(unknown))}")
    return arguments


def call_tool(
    name: str,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行一个分析工具，始终返回响应外壳，不抛异常。"""
    if name not in _TOOL_NAMES:
        return _reject(name, "UNKNOWN_TOOL", f"未知工具：{name}")

    try:
        args = _normalize_arguments(name, arguments)

        if name == "scenario.generate":
            prompt = args.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ToolArgumentError("INVALID_ARGUMENT", "prompt 不能为空")
            scenario_type = args.get("scenario_type")
            seed = args.get("seed")
            if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or seed < 0):
                raise ToolArgumentError("INVALID_ARGUMENT", "seed 必须是非负整数")
            include_evaluation = _validate_bool(args, "include_evaluation")
            scenario = generate_scenario(
                prompt,
                scenario_type=scenario_type,
                seed=seed,
                reference_date=args.get("reference_date"),
            )
            if not include_evaluation:
                scenario = _client_scenario(scenario)
            return _envelope(name, "succeeded", data=scenario)

        scenario = _resolve_scenario(args, data)

        if name == "bills.summary":
            month = _validate_month(args)
            year = _validate_year(args)
            if year is not None:
                payload = annual_report(scenario, year)
            elif month is not None:
                payload = monthly_report(scenario, month)
            else:
                payload = overall_summary(scenario)
            return _envelope(name, "succeeded", data=payload)

        if name == "bills.categories":
            payload = category_breakdown(
                scenario,
                month=_validate_month(args),
                year=_validate_year(args),
            )
            return _envelope(name, "succeeded", data=payload)

        if name == "anomalies.detect":
            return _envelope(name, "succeeded", data=detect_anomalies(scenario))

        if name == "subscriptions.burden":
            return _envelope(name, "succeeded", data=subscription_burden(scenario))

        if name == "cashflow.project":
            return _envelope(
                name, "succeeded",
                data=project_cashflow(scenario, days=_validate_days(args)),
            )

        if name == "liquidity.available":
            payload = available_liquidity(scenario, days=_validate_days(args))
            payload.pop("projection", None)
            return _envelope(name, "succeeded", data=payload)

        if name == "budget.advice":
            payload = budget_advice(
                scenario,
                days=_validate_days(args),
                month=_validate_month(args),
            )
            return _envelope(name, "succeeded", data=payload)

        if name == "analysis.pipeline":
            payload = run_pipeline(
                scenario=scenario,
                days=_validate_days(args),
                month=_validate_month(args),
                include_evaluation=_validate_bool(args, "include_evaluation"),
            )
            return _envelope(name, "succeeded", data=payload)

        return _reject(name, "UNKNOWN_TOOL", f"未知工具：{name}")
    except ToolArgumentError as exc:
        return _reject(name, exc.code, exc.message)
    except BridgeError as exc:
        return _reject(name, exc.code, exc.message)
    except (ValueError, TypeError) as exc:
        return _reject(name, "INVALID_ARGUMENT", str(exc))

    # 兜底：未预期异常也不把堆栈甩给主 Agent
    except Exception as exc:  # pragma: no cover
        return _reject(name, "TOOL_FAILED", f"工具执行失败：{exc}")


def tool_result_json(result: Dict[str, Any]) -> str:
    """把工具结果序列化成 JSON，便于写入日志或接口响应。"""
    return json.dumps(result, ensure_ascii=False, indent=2)
