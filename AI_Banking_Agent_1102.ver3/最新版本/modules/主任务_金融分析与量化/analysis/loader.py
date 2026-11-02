"""analysis.loader —— 读取场景文件，统一成"契约格式"。

支持三种输入：
1. `POST /api/scenarios/generate` 的完整响应（含 schema_version / data）；
2. 契约场景 JSON（金额为整数分、状态为 booked）；
3. 环境生成 Agent 直接保存的内部 JSON（金额为元、状态为 completed），
   会自动调用同机的 scenario_adapter 转换。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

# 环境生成 Agent 与本项目是同级目录
_ENV_DIR = Path(__file__).resolve().parents[2] / "环境生成agent"


def _looks_like_contract(scenario: Dict[str, Any]) -> bool:
    """契约场景的标志：有 currency，且交易金额带 amount_minor/direction。"""
    if scenario.get("currency") != "CNY":
        return False
    transactions = scenario.get("transactions") or []
    if not transactions:
        return True
    sample = transactions[0]
    return isinstance(sample, dict) and "amount_minor" in sample and "direction" in sample


def _convert_internal(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """内部元格式 -> 契约整数分格式。"""
    if not _ENV_DIR.exists():
        raise ValueError(
            f"发现内部格式场景，但找不到环境生成 Agent 目录：{_ENV_DIR}"
        )
    env_path = str(_ENV_DIR)
    if env_path not in sys.path:
        sys.path.insert(0, env_path)
    from scenario_adapter import to_contract_scenario  # type: ignore

    return to_contract_scenario(scenario)


def normalize_scenario(payload: Any) -> Dict[str, Any]:
    """把任意支持格式规范化成契约场景。"""
    if not isinstance(payload, dict):
        raise ValueError("场景数据必须是 JSON 对象")

    # 1) 完整 HTTP 响应
    if "schema_version" in payload and isinstance(payload.get("data"), dict):
        payload = payload["data"]

    if not isinstance(payload, dict):
        raise ValueError("响应里的 data 必须是 JSON 对象")

    # 2) 契约场景
    if _looks_like_contract(payload):
        return payload

    # 3) 环境生成 Agent 的内部场景
    if "scenario_type" in payload and "transactions" in payload:
        return _convert_internal(payload)

    raise ValueError("无法识别的场景格式（既不是契约格式，也不是环境生成 JSON）")


def load_scenario(path: str | Path) -> Dict[str, Any]:
    """从文件读取并规范化场景。"""
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return normalize_scenario(payload)
