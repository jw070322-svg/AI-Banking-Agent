"""bridge.py —— 主任务与环境生成 Agent 之间的桥。

完整逻辑链：

    自然语言需求
        ↓  环境生成 Agent（../环境生成agent）
    契约场景 JSON（整数分、booked、ledger_modified=false）
        ↓  分析内核（analysis/）
    账单报告 / 异常提醒 / 订阅负担 / 现金流 / 流动性
        ↓  tools.py
    主 Agent 可调用的工具结果

为什么要单独一层：
- 环境生成 Agent 是独立维护的模块，主任务不复制它的代码；
- 两者通过 **契约格式** 通信，不共享内部 dict 结构；
- 环境生成 Agent 升级时，只要契约不变，分析侧不需要改。
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
ENV_DIR = BASE_DIR.parent / "环境生成agent"

SCENARIO_TYPES = "ABCDEFG"
_MAX_PROMPT_LENGTH = 2000


class BridgeError(Exception):
    """桥接层错误（环境不可用、生成失败等）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_ENV_MODULES: Optional[Dict[str, Any]] = None


def _load_env_modules() -> Dict[str, Any]:
    """按需加载环境生成 Agent（只加载一次）。"""
    global _ENV_MODULES
    if _ENV_MODULES is not None:
        return _ENV_MODULES

    if not ENV_DIR.exists():
        raise BridgeError("ENVIRONMENT_UNAVAILABLE", f"找不到环境生成 Agent：{ENV_DIR}")

    env_path = str(ENV_DIR)
    if env_path not in sys.path:
        sys.path.insert(0, env_path)

    try:
        import main as env_main  # type: ignore
        from scenario_adapter import handle_generate, reset_idempotency_store  # type: ignore
    except ImportError as exc:  # pragma: no cover - 环境缺失时才会触发
        raise BridgeError("ENVIRONMENT_UNAVAILABLE", f"环境生成 Agent 导入失败：{exc}") from exc

    _ENV_MODULES = {
        "main": env_main,
        "handle_generate": handle_generate,
        "reset_idempotency_store": reset_idempotency_store,
    }
    return _ENV_MODULES


def environment_status() -> Dict[str, Any]:
    """检查环境生成 Agent 是否可用，供主服务启动时自检。"""
    try:
        modules = _load_env_modules()
    except BridgeError as exc:
        return {
            "available": False,
            "path": str(ENV_DIR),
            "error": {"code": exc.code, "message": exc.message},
        }

    env_main = modules["main"]
    return {
        "available": True,
        "path": str(ENV_DIR),
        "scenario_types": list(SCENARIO_TYPES),
        "scenario_names": {
            key: value for key, value in env_main.SCENARIO_TYPE_NAMES.items()
        },
        "schema_version": "1.0.0",
    }


def _scenario_key(payload: Dict[str, Any], seed: Optional[int]) -> str:
    """生成幂等键：固定 seed 时确定性，未指定 seed 时每次新生成。"""
    if seed is None:
        return f"bridge-{uuid.uuid4().hex}"
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "bridge-" + hashlib.sha256(material).hexdigest()[:24]


def generate_scenario_response(
    prompt: str,
    *,
    scenario_type: Optional[str] = None,
    seed: Optional[int] = None,
    reference_date: Optional[str] = None,
    session_id: str = "main-task",
) -> Dict[str, Any]:
    """调用环境生成 Agent，返回完整的契约响应外壳。"""
    if not isinstance(prompt, str) or not prompt.strip():
        raise BridgeError("INVALID_ARGUMENT", "prompt 不能为空")
    if len(prompt) > _MAX_PROMPT_LENGTH:
        raise BridgeError("INVALID_ARGUMENT", f"prompt 不能超过 {_MAX_PROMPT_LENGTH} 字")

    modules = _load_env_modules()
    payload = {
        "prompt": prompt.strip(),
        "scenario_type": scenario_type,
        "seed": seed,
        "reference_date": reference_date,
    }
    response = modules["handle_generate"](
        payload,
        idempotency_key=_scenario_key(payload, seed),
        session_id=session_id,
    )
    if response.get("status") != "succeeded":
        error = response.get("error") or {}
        raise BridgeError(
            error.get("code", "SCENARIO_GENERATION_FAILED"),
            error.get("message", "场景生成失败"),
        )
    return response


def generate_scenario(
    prompt: str,
    *,
    scenario_type: Optional[str] = None,
    seed: Optional[int] = None,
    reference_date: Optional[str] = None,
) -> Dict[str, Any]:
    """只返回契约场景数据，供分析内核使用。"""
    return generate_scenario_response(
        prompt,
        scenario_type=scenario_type,
        seed=seed,
        reference_date=reference_date,
    )["data"]


def generate_all(
    seed: int = 42,
    reference_date: str = "2026-10-23",
) -> Dict[str, Dict[str, Any]]:
    """一次生成 A~G 七类契约场景，返回 {类型: 场景}。"""
    env_main = _load_env_modules()["main"]
    return {
        scenario_type: generate_scenario(
            env_main.DEFAULT_REQUIREMENTS[scenario_type],
            scenario_type=scenario_type,
            seed=seed,
            reference_date=reference_date,
        )
        for scenario_type in SCENARIO_TYPES
    }


def save_scenario(scenario: Dict[str, Any], path: str | Path) -> Path:
    """把契约场景保存为 JSON（评测/回归用）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


def scenario_types() -> List[str]:
    return list(SCENARIO_TYPES)


def reset_generation_cache() -> None:
    """清空环境生成侧的幂等缓存（测试用）。"""
    _load_env_modules()["reset_idempotency_store"]()
