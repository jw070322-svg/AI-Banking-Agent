"""scenario_adapter.py —— 把环境生成 Agent 适配成 FirstAgent 统一接口 1.0.0
=============================================================================

为什么需要这一层？
------------------
比赛里各模块的数据单位不一样：vv 用"整数分"，eva 用 Decimal 元，推荐模块用元。
API-CONTRACT(1).md 规定所有新分支以统一契约为接入基线，所以本文件负责：

1. 金额统一换成 **整数分**（CNY minor units），并拒绝 bool、字符串、浮点、
   负数和超过两位小数的值；
2. 交易状态统一：内部 completed -> 对外 booked（表示已入账）；
3. 输出不包含顾客身份证、手机号、邮箱、住址、完整卡号等原始个人信息；
4. 返回统一响应外壳：schema_version / request_id / status / data / error /
   trace / simulated；
5. 支持 Idempotency-Key：同会话同 key 同参数返回原响应，改参复用 key 报
   IDEMPOTENCY_CONFLICT；
6. 场景校验失败时返回 SCENARIO_INVALID，并且绝不写入真实演示账本
   （输出恒为 ledger_modified: false）。

金额字段约定（与契约一致）
--------------------------
- `amount_minor`：交易金额的绝对值，整数分，**永远 >= 0**；
- `amount`：账单视角的带符号金额，整数分，支出/转出为负、收入/转入/退款为正；
- 账户用 `initial_balance_minor` / `balance_minor`。

用法示例
--------
>>> response = handle_generate({"prompt": "生成一个疑似重复扣款场景"}, idempotency_key="k1")
>>> response["status"]
'succeeded'
>>> response["data"]["transactions"][0]["amount_minor"]  # 整数分
...
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import main

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0.0"
MAX_PROMPT_LENGTH = 2000
MAX_IDEMPOTENCY_KEY_LENGTH = 200
MAX_SEED = 2 ** 32 - 1
SUPPORTED_SCENARIO_TYPES = ("A", "B", "C", "D", "E", "F", "G")

# 内部状态 -> 契约状态。booked 表示已入账，会参与余额计算。
STATUS_MAP = {
    "completed": "booked",
    "booked": "booked",
    "pending": "pending",
    "rejected": "rejected",
    "failed": "failed",
    "reversed": "reversed",
}

SUCCESS = "succeeded"
REJECTED = "rejected"
FAILED = "failed"

# 幂等存储：SQLite 持久化，重启后仍能重放原响应。
# 路径优先级：configure_idempotency_store() > ENV_AGENT_IDEMPOTENCY_DB 环境变量 > runtime/ 默认路径。
_DEFAULT_IDEMPOTENCY_DB = Path(__file__).resolve().parent / "runtime" / "idempotency.sqlite3"
_IDEMPOTENCY_DB_PATH = Path(
    os.environ.get("ENV_AGENT_IDEMPOTENCY_DB", str(_DEFAULT_IDEMPOTENCY_DB))
)
_IDEMPOTENCY_CONN: Optional[sqlite3.Connection] = None
_IDEMPOTENCY_LOCK = threading.Lock()

# 生成过程会临时设置全局随机种子 / 参考日期，用锁避免并发请求互相干扰
_GENERATE_LOCK = threading.Lock()


class RequestError(Exception):
    """请求参数不合法（对应契约里的 INVALID_ARGUMENT）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 1. 金额转换与校验
# ---------------------------------------------------------------------------

def to_minor(value: Any, field: str = "amount") -> int:
    """把"元"转成"整数分"，同时拒绝契约禁止的输入类型。

    允许：int（非 bool）、float（有限、非负、最多两位小数）。
    拒绝：bool、str、None、NaN、inf、负数、三位以上小数。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestError("INVALID_ARGUMENT", f"{field} 必须是数字（整数分换算前的人民币元）")
    if not math.isfinite(value):
        raise RequestError("INVALID_ARGUMENT", f"{field} 必须是有限数字")
    if value < 0:
        raise RequestError("INVALID_ARGUMENT", f"{field} 不能为负数")
    cents = value * 100
    minor = int(round(cents))
    if abs(cents - minor) > 1e-6:
        raise RequestError("INVALID_ARGUMENT", f"{field} 最多保留两位小数")
    return minor


def _optional_minor(value: Any, field: str) -> Optional[int]:
    """可选金额字段：None 原样返回，其余走 to_minor。"""
    if value is None:
        return None
    return to_minor(value, field)


# ---------------------------------------------------------------------------
# 2. 内部场景 -> 契约场景
# ---------------------------------------------------------------------------

def _contract_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """只输出去标识化后的用户画像，不包含身份证/手机/邮箱/住址。"""
    profile: Dict[str, Any] = {
        "occupation": user.get("occupation"),
        "registration_date": user.get("registration_date"),
    }
    monthly_income = user.get("monthly_income")
    if isinstance(monthly_income, (int, float)) and not isinstance(monthly_income, bool):
        profile["monthly_income_minor"] = to_minor(monthly_income, "monthly_income")
    return {"user_id": user.get("user_id"), "profile": profile}


def _contract_account(account: Dict[str, Any]) -> Dict[str, Any]:
    """账户转整数分；不输出 account_number。"""
    return {
        "account_id": account.get("account_id"),
        "user_id": account.get("user_id"),
        "account_type": account.get("account_type"),
        "currency": account.get("currency", "CNY"),
        "initial_balance_minor": to_minor(account.get("initial_balance", 0), "initial_balance"),
        "balance_minor": to_minor(account.get("balance", 0), "balance"),
        "status": account.get("status"),
        "opened_date": account.get("opened_date"),
    }


def _contract_transaction(transaction: Dict[str, Any]) -> Dict[str, Any]:
    """单笔交易转契约格式。

    - amount_minor：绝对值，整数分；
    - amount：带符号整数分（支出/转出为负，收入/转入/退款为正）；
    - status：completed -> booked。
    """
    transaction_type = transaction.get("transaction_type")
    abs_minor = to_minor(transaction.get("amount", 0), f"交易 {transaction.get('transaction_id')} 的金额")

    if transaction_type in ("expense", "transfer_out"):
        signed_minor = -abs_minor
        direction = "debit"
    elif transaction_type in ("income", "transfer_in", "refund"):
        signed_minor = abs_minor
        direction = "credit"
    else:
        # validator 会在生成阶段拦住非法类型，这里只是兜底
        signed_minor = abs_minor
        direction = "unknown"

    status = STATUS_MAP.get(transaction.get("status", "completed"))
    if status is None:
        raise RequestError(
            "SCENARIO_INVALID",
            f"交易 {transaction.get('transaction_id')} 的状态无法映射：{transaction.get('status')}",
        )

    contract: Dict[str, Any] = {
        "transaction_id": transaction.get("transaction_id"),
        "account_id": transaction.get("account_id"),
        "date": transaction.get("date"),
        "amount_minor": abs_minor,
        "amount": signed_minor,
        "direction": direction,
        "transaction_type": transaction_type,
        "category": transaction.get("category"),
        "merchant": transaction.get("merchant"),
        "description": transaction.get("description"),
        "status": status,
    }

    # 场景语义字段：只在存在时输出，避免主 Agent 读到一堆 null
    for field in (
        "time", "is_suspicious", "duplicate_group_id", "related_transaction_id",
        "expected_result", "subscription_type", "subscription_cycle", "recurring",
    ):
        if field in transaction:
            contract[field] = transaction[field]

    return contract


def _contract_summary(transactions: List[Dict[str, Any]]) -> Dict[str, int]:
    """按已入账（booked）交易汇总，方便账单分析场景直接使用（整数分）。"""
    income_minor = 0
    expense_minor = 0
    for transaction in transactions:
        if transaction["status"] != "booked":
            continue
        if transaction["direction"] == "credit":
            income_minor += transaction["amount_minor"]
        elif transaction["direction"] == "debit":
            expense_minor += transaction["amount_minor"]
    return {
        "transaction_count": len(transactions),
        "booked_income_minor": income_minor,
        "booked_expense_minor": expense_minor,
        "booked_net_minor": income_minor - expense_minor,
    }


def _contract_budget(budget: Dict[str, Any]) -> Dict[str, Any]:
    """场景 F 的预算字段转整数分（缺失字段不输出，避免 null 混进契约）。"""
    contract: Dict[str, Any] = {
        "currency": budget.get("currency", "CNY"),
        "lock_month": budget.get("lock_month"),
    }
    monthly = _optional_minor(budget.get("monthly_activity_budget"), "monthly_activity_budget")
    locked = _optional_minor(budget.get("locked_amount"), "locked_amount")
    if monthly is not None:
        contract["monthly_activity_budget_minor"] = monthly
    if locked is not None:
        contract["locked_amount_minor"] = locked
    return contract


def _contract_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """卡片转契约格式：额度类字段统一为整数分，卡号保持脱敏。"""
    contract: Dict[str, Any] = {
        "card_id": card.get("card_id"),
        "user_id": card.get("user_id"),
        "account_id": card.get("account_id"),
        "card_type": card.get("card_type"),
        "card_number_masked": card.get("card_number_masked"),
        "brand": card.get("brand"),
        "status": card.get("status"),
        "currency": card.get("currency", "CNY"),
        "opened_date": card.get("opened_date"),
    }
    for field in ("credit_limit", "used_credit", "available_credit"):
        if field in card:
            contract[f"{field}_minor"] = to_minor(card[field], field)
    for field in ("statement_day", "due_day"):
        if field in card:
            contract[field] = card[field]

    limits = card.get("transaction_limit")
    if isinstance(limits, dict):
        contract["transaction_limit_minor"] = {
            "daily_minor": to_minor(limits.get("daily", 0), "transaction_limit.daily"),
            "single_minor": to_minor(limits.get("single", 0), "transaction_limit.single"),
        }
    return contract


def _contract_bill_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """信用卡账单明细转契约格式（支出为负、退款为正）。"""
    abs_minor = to_minor(item.get("amount", 0), f"账单明细 {item.get('transaction_id')}")
    item_type = item.get("transaction_type")
    if item_type == "expense":
        signed_minor = -abs_minor
        direction = "debit"
    else:
        signed_minor = abs_minor
        direction = "credit"
    return {
        "transaction_id": item.get("transaction_id"),
        "card_id": item.get("card_id"),
        "date": item.get("date"),
        "amount_minor": abs_minor,
        "amount": signed_minor,
        "direction": direction,
        "transaction_type": item_type,
        "category": item.get("category"),
        "merchant": item.get("merchant"),
        "description": item.get("description"),
        "status": "booked",
    }


def _contract_card_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """卡片事件里的 before/after 快照：金额同样转整数分。"""
    converted: Dict[str, Any] = {}
    for key, value in snapshot.items():
        if key in ("credit_limit", "used_credit", "available_credit"):
            converted[f"{key}_minor"] = to_minor(value, key)
        elif key == "transaction_limit" and isinstance(value, dict):
            converted["transaction_limit_minor"] = {
                "daily_minor": to_minor(value.get("daily", 0), "transaction_limit.daily"),
                "single_minor": to_minor(value.get("single", 0), "transaction_limit.single"),
            }
        else:
            converted[key] = value
    return converted


def _contract_card_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """卡片事件转契约格式。"""
    converted: List[Dict[str, Any]] = []
    for event in events:
        converted.append({
            "event_id": event.get("event_id"),
            "card_id": event.get("card_id"),
            "date": event.get("date"),
            "event_type": event.get("event_type"),
            "status": event.get("status"),
            "before": _contract_card_snapshot(event.get("before") or {}),
            "after": _contract_card_snapshot(event.get("after") or {}),
            "reason": event.get("reason"),
        })
    return converted


def _contract_credit_card_bill(bill: Dict[str, Any]) -> Dict[str, Any]:
    """信用卡账单转契约格式。"""
    return {
        "bill_id": bill.get("bill_id"),
        "card_id": bill.get("card_id"),
        "cycle_start": bill.get("cycle_start"),
        "statement_date": bill.get("statement_date"),
        "due_date": bill.get("due_date"),
        "currency": bill.get("currency", "CNY"),
        "status": bill.get("status"),
        "items": [_contract_bill_item(item) for item in bill.get("items", [])],
        "total_amount_minor": to_minor(bill.get("total_amount", 0), "total_amount"),
        "minimum_payment_minor": to_minor(bill.get("minimum_payment", 0), "minimum_payment"),
        "paid_amount_minor": to_minor(bill.get("paid_amount", 0), "paid_amount"),
        "outstanding_amount_minor": to_minor(bill.get("outstanding_amount", 0), "outstanding_amount"),
    }


def _contract_subscriptions(subscriptions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """订阅区块转契约格式。"""
    return [
        {
            "subscription_id": subscription.get("subscription_id"),
            "merchant": subscription.get("merchant"),
            "amount_minor": to_minor(subscription.get("amount", 0), "subscription.amount"),
            "cycle": subscription.get("cycle"),
            "category": subscription.get("category"),
            "subscription_type": subscription.get("subscription_type"),
            "last_charge_date": subscription.get("last_charge_date"),
            "next_charge_date": subscription.get("next_charge_date"),
            "status": subscription.get("status"),
        }
        for subscription in subscriptions
    ]


def _contract_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """日历事件转契约格式（预算字段转整数分）。"""
    converted: List[Dict[str, Any]] = []
    for event in events:
        item = {
            "event_id": event.get("event_id"),
            "date": event.get("date"),
            "event_type": event.get("event_type"),
            "category": event.get("category"),
            "title": event.get("title"),
            "related_member_id": event.get("related_member_id"),
            "related_card_id": event.get("related_card_id"),
            "related_subscription_id": event.get("related_subscription_id"),
            "remind_days_before": event.get("remind_days_before"),
            "remind_date": event.get("remind_date"),
            "priority": event.get("priority"),
            "status": event.get("status"),
            "notes": event.get("notes"),
        }
        if event.get("budget") is not None:
            item["budget_minor"] = to_minor(event["budget"], "calendar.budget")
        converted.append(item)
    return converted


def _contract_calendar(calendar: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """场景 F 的活动日历转整数分。"""
    entries: List[Dict[str, Any]] = []
    for entry in calendar:
        entries.append({
            "event_id": entry.get("event_id"),
            "date": entry.get("date"),
            "title": entry.get("title"),
            "category": entry.get("category"),
            "budget_minor": to_minor(entry.get("budget", 0), "活动日历预算"),
            "status": entry.get("status"),
            "related_member_id": entry.get("related_member_id"),
            "auto_order": entry.get("auto_order", False),
        })
    return entries


def to_contract_scenario(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """把内部场景（元、completed）转换成统一契约场景（整数分、booked）。"""
    transactions = [_contract_transaction(t) for t in scenario.get("transactions", [])]
    accounts = [_contract_account(a) for a in scenario.get("accounts", [])]

    contract: Dict[str, Any] = {
        "scenario_id": scenario.get("scenario_id"),
        "scenario_type": scenario.get("scenario_type"),
        "scenario_name": scenario.get("scenario_name"),
        "created_at": scenario.get("created_at"),
        "currency": "CNY",
        "ledger_modified": False,          # 只生成独立数据，不写入演示账本
        "user": _contract_user(scenario.get("user", {})),
        "accounts": accounts,
        "transactions": transactions,
        "summary": _contract_summary(transactions),
        "scenario_requirements": scenario.get("scenario_requirements", {}),
    }

    if "cards" in scenario:
        contract["cards"] = [_contract_card(card) for card in scenario.get("cards", [])]
    if "credit_card_bill" in scenario:
        contract["credit_card_bill"] = _contract_credit_card_bill(scenario["credit_card_bill"])
    if "card_events" in scenario:
        contract["card_events"] = _contract_card_events(scenario.get("card_events", []))
    if "subscriptions" in scenario:
        contract["subscriptions"] = _contract_subscriptions(scenario.get("subscriptions", []))
    if "calendar_events" in scenario:
        contract["calendar_events"] = _contract_events(scenario.get("calendar_events", []))
    if "expected_insights" in scenario:
        contract["expected_insights"] = scenario.get("expected_insights", [])
        # 这是"标准答案"，只用于评估分析 Agent，不应出现在面向客户的回答里
        contract["evaluation_only_fields"] = ["expected_insights"]

    if "family" in scenario:
        contract["family"] = [
            {
                "member_id": member.get("member_id"),
                "relation": member.get("relation"),
                "birthday": member.get("birthday"),
                "birth_year": member.get("birth_year"),
                "age_turning": member.get("age_turning"),
            }
            for member in scenario.get("family", [])
        ]
    if "budget" in scenario:
        contract["budget"] = _contract_budget(scenario.get("budget", {}))
    if "activity_calendar" in scenario:
        contract["activity_calendar"] = _contract_calendar(scenario.get("activity_calendar", []))

    _assert_integer_minor(contract)
    return contract


# 允许为负的整数分字段：账单带符号金额、已入账净额
SIGNED_MINOR_KEYS = {"amount", "booked_net_minor"}


def _assert_integer_minor(value: Any, path: str = "data") -> None:
    """递归检查输出里所有金额字段都是整数分，防止 float 漏到契约边界上。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                # 例如 transaction_limit_minor 是嵌套字典，继续往里检查
                _assert_integer_minor(item, f"{path}.{key}")
            elif key.endswith("_minor") or key == "amount":
                if isinstance(item, bool) or not isinstance(item, int):
                    raise RequestError("SCENARIO_INVALID", f"{path}.{key} 必须是整数分")
                if item < 0 and key not in SIGNED_MINOR_KEYS:
                    raise RequestError("SCENARIO_INVALID", f"{path}.{key} 不能为负数")
            else:
                _assert_integer_minor(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_integer_minor(item, f"{path}[{index}]")


# ---------------------------------------------------------------------------
# 3. 请求规范化与生成
# ---------------------------------------------------------------------------

def _normalize_request(request: Any) -> Dict[str, Any]:
    """校验并规范化请求参数。

    支持的字段：
    - prompt（必填）：自然语言需求，1~2000 字；
    - scenario_type（可选）：A~F，显式指定时以它为准；
    - seed（可选）：0 ~ 2^32-1 的整数，用于复现；
    - reference_date（可选）：YYYY-MM-DD，固定生成时的"今天"。
    """
    if not isinstance(request, dict):
        raise RequestError("INVALID_ARGUMENT", "请求体必须是 JSON 对象")

    if "prompt" not in request:
        raise RequestError("INVALID_ARGUMENT", "缺少 prompt")

    prompt = request["prompt"]
    if not isinstance(prompt, str):
        raise RequestError("INVALID_ARGUMENT", "prompt 必须是字符串")
    prompt = prompt.strip()
    if not prompt:
        raise RequestError("INVALID_ARGUMENT", "prompt 不能为空")
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise RequestError("INVALID_ARGUMENT", f"prompt 不能超过 {MAX_PROMPT_LENGTH} 字")

    scenario_type = request.get("scenario_type")
    if scenario_type is not None:
        if not isinstance(scenario_type, str) or scenario_type not in SUPPORTED_SCENARIO_TYPES:
            raise RequestError(
                "INVALID_ARGUMENT",
                f"scenario_type 必须是 {'/'.join(SUPPORTED_SCENARIO_TYPES)} 之一",
            )

    seed = request.get("seed")
    if seed is not None:
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
            raise RequestError("INVALID_ARGUMENT", f"seed 必须是 0~{MAX_SEED} 的整数")

    reference_date = request.get("reference_date")
    if reference_date is not None:
        if not isinstance(reference_date, str):
            raise RequestError("INVALID_ARGUMENT", "reference_date 必须是 YYYY-MM-DD 字符串")
        try:
            datetime.strptime(reference_date, "%Y-%m-%d")
        except ValueError:
            raise RequestError("INVALID_ARGUMENT", "reference_date 必须是合法的 YYYY-MM-DD") from None

    return {
        "prompt": prompt,
        "scenario_type": scenario_type,
        "seed": seed,
        "reference_date": reference_date,
    }


def _build_config(params: Dict[str, Any]) -> Dict[str, Any]:
    """把请求参数解析成 main.py 使用的场景配置。"""
    config = main.parse_requirement(params["prompt"])

    # 显式指定的场景类型优先（用于评测时直接点名场景）
    if params["scenario_type"] and params["scenario_type"] != config["scenario_type"]:
        scenario_type = params["scenario_type"]
        config["scenario_type"] = scenario_type
        config["scenario_name"] = main.SCENARIO_TYPE_NAMES[scenario_type]
        # 需求里解析到的金额要带进目标场景，不能因为显式指定类型而丢掉
        if scenario_type == "B" and "increase_amount" not in config["params"]:
            config["params"]["increase_amount"] = config["params"].get("amount", 800.0)
        if scenario_type == "F" and "monthly_activity_budget" not in config["params"]:
            config["params"]["monthly_activity_budget"] = config["params"].get("amount", 1000.0)
        config["requirements"] = main.build_requirements(scenario_type, config["params"])

    config["scenario_id"] = main.generate_scenario_id(config["scenario_type"])
    return config


def _generate(params: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """在锁内生成并双层的校验场景，返回 (内部场景, config)。

    为什么加锁：main.py 的随机种子和参考日期是全局状态。多线程同时调用会
    互相污染，所以这里串行生成，并保证结束后恢复原来的设置。
    """
    with _GENERATE_LOCK:
        previous_seed = main._RANDOM_SEED
        previous_reference = main._REFERENCE_NOW
        try:
            main.set_seed(params["seed"])
            main.set_reference_date(params["reference_date"])

            config = _build_config(params)
            scenario = main.generate_scenario(config)
            ok, messages = main.validate_scenario(scenario, config)
            if not ok:
                raise RequestError("SCENARIO_INVALID", "; ".join(messages))
            return scenario, config
        finally:
            main.set_seed(previous_seed)
            main.set_reference_date(
                previous_reference.strftime("%Y-%m-%d") if previous_reference else None
            )


# ---------------------------------------------------------------------------
# 4. 响应外壳与幂等
# ---------------------------------------------------------------------------

def _request_id() -> str:
    """生成请求 ID（与业务 scenario_id 区分开）。"""
    return f"REQ-{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8].upper()}"


def _envelope(
    status: str,
    *,
    data: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, str]] = None,
    trace: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造契约规定的响应外壳。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": _request_id(),
        "status": status,
        "data": data,
        "error": error,
        "trace": trace or {},
        "simulated": True,
    }


def _error_envelope(status: str, code: str, message: str, trace: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _envelope(status, error={"code": code, "message": message}, trace=trace)


def _validate_idempotency_key(idempotency_key: Any) -> Optional[str]:
    """校验 Idempotency-Key；不传则返回 None（不做幂等）。"""
    if idempotency_key is None:
        return None
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise RequestError("INVALID_ARGUMENT", "Idempotency-Key 必须是非空字符串")
    if len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise RequestError(
            "INVALID_ARGUMENT", f"Idempotency-Key 不能超过 {MAX_IDEMPOTENCY_KEY_LENGTH} 字符"
        )
    return idempotency_key


def _canonical_params(params: Dict[str, Any]) -> str:
    """把请求参数规范化成稳定字符串，用于判断"同 key 是否同参数"。"""
    return json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _idempotency_connection() -> sqlite3.Connection:
    """懒加载 SQLite 连接并建表；调用方负责持有 _IDEMPOTENCY_LOCK。"""
    global _IDEMPOTENCY_CONN
    if _IDEMPOTENCY_CONN is not None:
        return _IDEMPOTENCY_CONN
    path = _IDEMPOTENCY_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS idempotency (
            session_id TEXT NOT NULL,
            key TEXT NOT NULL,
            params TEXT NOT NULL,
            response TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (session_id, key)
        )
        """
    )
    connection.commit()
    _IDEMPOTENCY_CONN = connection
    return connection


def configure_idempotency_store(path: Optional[str | Path] = None) -> None:
    """切换幂等库路径并关闭旧连接；path=None 时恢复默认路径。

    测试用临时库、部署时指定持久化目录都通过它完成。
    """
    global _IDEMPOTENCY_DB_PATH, _IDEMPOTENCY_CONN
    with _IDEMPOTENCY_LOCK:
        if _IDEMPOTENCY_CONN is not None:
            _IDEMPOTENCY_CONN.close()
            _IDEMPOTENCY_CONN = None
        if path is None:
            _IDEMPOTENCY_DB_PATH = Path(
                os.environ.get("ENV_AGENT_IDEMPOTENCY_DB", str(_DEFAULT_IDEMPOTENCY_DB))
            )
        else:
            _IDEMPOTENCY_DB_PATH = Path(path)


def reset_idempotency_store() -> None:
    """清空幂等记录（测试用），不删除数据库文件本身。"""
    with _IDEMPOTENCY_LOCK:
        connection = _idempotency_connection()
        connection.execute("DELETE FROM idempotency")
        connection.commit()


def handle_generate(
    request: Any,
    *,
    idempotency_key: Optional[str] = None,
    session_id: str = "demo",
) -> Dict[str, Any]:
    """处理 POST /api/scenarios/generate 的核心逻辑（纯函数式，可直接单测）。

    参数：
    - request：请求体 dict（见 _normalize_request）；
    - idempotency_key：契约要求 POST 必须携带；不传时本函数仍可工作，方便内部测试；
    - session_id：演示会话 ID；幂等键按会话隔离，不能跨会话复用。

    返回：契约响应外壳。失败时不抛异常，而是返回 status=rejected/failed。
    """
    started = time.perf_counter()
    base_trace: Dict[str, Any] = {"generator": "environment-agent"}

    try:
        key = _validate_idempotency_key(idempotency_key)
    except RequestError as exc:
        return _error_envelope(REJECTED, exc.code, exc.message, base_trace)

    try:
        params = _normalize_request(request)
    except RequestError as exc:
        return _error_envelope(REJECTED, exc.code, exc.message, base_trace)

    # 幂等检查：同会话 + 同 key + 同参数 -> 直接返回持久化响应
    store_key: Optional[Tuple[str, str]] = (session_id, key) if key else None
    canonical_params = _canonical_params(params) if store_key else None
    if store_key is not None:
        try:
            with _IDEMPOTENCY_LOCK:
                connection = _idempotency_connection()
                row = connection.execute(
                    "SELECT params, response FROM idempotency "
                    "WHERE session_id=? AND key=?",
                    store_key,
                ).fetchone()
        except sqlite3.Error as exc:
            return _error_envelope(
                FAILED,
                "IDEMPOTENCY_STORE_UNAVAILABLE",
                f"幂等存储不可用：{exc}",
                base_trace,
            )
        if row is not None:
            if row[0] == canonical_params:
                return json.loads(row[1])
            return _error_envelope(
                REJECTED,
                "IDEMPOTENCY_CONFLICT",
                "同一 Idempotency-Key 不能用于不同的请求参数",
                base_trace,
            )

    try:
        scenario, config = _generate(params)
        data = to_contract_scenario(scenario)
    except RequestError as exc:
        status = REJECTED if exc.code in ("SCENARIO_INVALID", "INVALID_ARGUMENT") else FAILED
        return _error_envelope(status, exc.code, exc.message, base_trace)
    except main.ScenarioError as exc:
        return _error_envelope(REJECTED, "SCENARIO_UNSUPPORTED", str(exc), base_trace)
    except Exception as exc:  # 兜底：不把堆栈暴露给调用方
        return _error_envelope(FAILED, "SCENARIO_GENERATION_FAILED", f"场景生成失败：{exc}", base_trace)

    trace = {
        "generator": "environment-agent",
        "scenario_type": data["scenario_type"],
        "seed": params["seed"],
        "reference_date": params["reference_date"],
        "validation": {"layers": ["validator", "fallback"], "passed": True},
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    response = _envelope(SUCCESS, data=data, trace=trace)

    if store_key is not None:
        try:
            with _IDEMPOTENCY_LOCK:
                connection = _idempotency_connection()
                connection.execute(
                    "INSERT OR REPLACE INTO idempotency "
                    "(session_id, key, params, response, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        session_id,
                        key,
                        canonical_params,
                        json.dumps(response, ensure_ascii=False),
                        time.time(),
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            return _error_envelope(
                FAILED,
                "IDEMPOTENCY_STORE_UNAVAILABLE",
                f"幂等存储不可用：{exc}",
                trace,
            )

    return response
