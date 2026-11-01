#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py —— 银行场景环境生成 Agent 的入口文件
=====================================================

职责（本文件做什么）：
1. 与用户交互，接收自然语言描述的银行场景需求；
2. 用关键词 / 规则把需求解析成结构化场景配置（第一版不接大模型）；
3. 调用场景生成模块（scenario_generator）生成场景数据；
4. 调用校验模块（validator）检查生成结果是否满足场景目标；
5. 校验通过后，把场景保存为 JSON 文件（pathlib + json）；
6. 在终端输出场景 ID、场景类型、文件路径和校验结果；
7. 捕获常见错误，支持连续创建多个场景，输入 exit 退出。

边界说明（重要）：
- 本 Agent 只负责"生成虚拟银行业务场景数据"，供主 Agent 读取使用；
- 所有数据均为虚构，不连接真实银行，不执行真实资金操作；
- 本 Agent 不负责回答银行用户的业务问题（那是主 Agent 的工作）。
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
import uuid

import banking_domain
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ============================================================================
# 0. 路径、常量与自定义异常
# ============================================================================

# 项目根目录：main.py 所在目录，所有路径都基于它
BASE_DIR = Path(__file__).resolve().parent

# 生成结果统一输出到 output 目录
OUTPUT_DIR = BASE_DIR / "output"

# 支持的场景：类型代码 -> 中文名
SCENARIO_TYPE_NAMES: Dict[str, str] = {
    "A": "普通银行用户",
    "B": "购物支出增加",
    "C": "疑似重复扣款",
    "D": "余额不足",
    "E": "周期性订阅",
    "F": "家庭生日跨场景联动",
    "G": "信用卡与卡片管理",
}

# 合法的交易类型（金额统一非负，用类型区分方向）
VALID_TRANSACTION_TYPES = {
    "income",        # 收入（如工资）：余额增加
    "expense",       # 支出（如购物、餐饮）：余额减少
    "transfer_in",   # 转入（从其他账户转入）：余额增加，内部转账不算消费
    "transfer_out",  # 转出（转给其他账户）：余额减少，内部转账不算消费
    "refund",        # 退款（商家退款）：余额增加
}

# 用户退出指令
EXIT_KEYWORDS = {"exit", "quit", "q", "退出"}

# 可复现设置：同一个 seed + 同一个参考日期，生成结果一致，方便评测和回归测试。
_RANDOM_SEED: Optional[int] = None
_REFERENCE_NOW: Optional[datetime] = None


def set_seed(seed: Optional[int]) -> None:
    """设置随机种子。传入 None 表示恢复真正的随机。

    举例：set_seed(42) 后，同样的需求会生成同样的金额和商户组合。
    """
    global _RANDOM_SEED
    _RANDOM_SEED = seed
    if seed is not None:
        random.seed(seed)


def set_reference_date(reference_date: Optional[str]) -> None:
    """设置生成时使用的"今天"。传入 None 表示使用真实的当前时间。

    举例：set_reference_date("2026-10-23") 后，所有日期都以这一天为基准计算，
    这样换一天运行也不会让样例的月份变化。
    """
    global _REFERENCE_NOW
    if reference_date is None:
        _REFERENCE_NOW = None
        return
    parsed = datetime.strptime(reference_date, "%Y-%m-%d")
    _REFERENCE_NOW = parsed


def _now() -> datetime:
    """返回生成逻辑使用的"当前时间"（可被 set_reference_date 固定）。"""
    return _REFERENCE_NOW if _REFERENCE_NOW is not None else datetime.now()


class ScenarioError(Exception):
    """环境生成 Agent 的业务异常（如不支持的场景、参数缺失等）。"""


# ============================================================================
# 1. 预留模块接口（可选导入）
# ============================================================================
# 下面三个模块是项目后续要开发的模块，main.py 会优先调用它们：
#   scenario_generator.py  ->  负责生成场景
#   validator.py           ->  负责校验场景
#   models.py              ->  负责定义数据结构
#
# 约定接口（模块作者必须遵守，否则 main.py 无法对接）：
#   scenario_generator.generate(config) -> dict
#       输入场景配置，返回完整场景 dict（必须能被 json 序列化）。
#   validator.validate(scenario, config) -> (bool, list[str])
#       返回 (是否通过, 消息列表)。
#
# 如果这些文件还不存在，就启用本文件内置的"临时实现"，保证程序先跑起来。

HAS_GENERATOR_MODULE = False
HAS_VALIDATOR_MODULE = False
HAS_MODELS_MODULE = False

try:
    import scenario_generator  # type: ignore
    HAS_GENERATOR_MODULE = True
except ImportError:
    pass

try:
    import validator  # type: ignore
    HAS_VALIDATOR_MODULE = True
except ImportError:
    pass

try:
    import models  # type: ignore
    HAS_MODELS_MODULE = True
except ImportError:
    pass


# ============================================================================
# 2. 需求解析（关键词 / 规则，第一版不接大模型）
# ============================================================================

def parse_requirement(text: str) -> Dict[str, Any]:
    """把用户输入的自然语言需求解析成结构化场景配置。

    返回结构：
    {
        "scenario_type": "A",                 # 场景类型代码 A~E
        "scenario_name": "普通银行用户",        # 场景中文名
        "params": {"increase_amount": 800.0}, # 场景专属参数
        "requirements": {...}                 # 场景目标与预期条件
    }
    """
    text = (text or "").strip()
    if not text:
        raise ScenarioError("需求为空，请描述你要生成的银行场景。")

    # 提取金额（例如"增加 800 元" -> 800.0），找不到就使用默认值 800
    amount_match = re.search(r"(\d+(?:\.\d+)?)\s*元?", text)
    increase_amount = float(amount_match.group(1)) if amount_match else 800.0

    # 关键词识别：从"最具体"到"最泛"依次判断
    scenario_type: Optional[str] = None
    if any(k in text for k in ("重复扣款", "重复扣费", "重复交易", "重复支付")):
        scenario_type = "C"
    elif any(k in text for k in ("余额不足", "无法完成转账", "转账失败", "余额不够")):
        scenario_type = "D"
    elif any(k in text for k in ("订阅", "周期性", "定期扣款")):
        scenario_type = "E"
    elif "购物" in text and any(k in text for k in ("增加", "上涨", "比上", "提升", "变多")):
        scenario_type = "B"
    elif any(k in text for k in ("生日", "鲜花", "蛋糕", "活动日历", "跨场景")):
        # 比赛"跨场景联动"：检测家人生日、锁定活动预算、生日前 2 天订购鲜花蛋糕
        scenario_type = "F"
    elif any(k in text for k in (
        "信用卡", "银行卡", "卡片", "挂失", "冻结", "解冻", "额度调整", "交易限制", "还款",
    )):
        # 比赛"卡片管理"：信用卡账单、挂失/冻结/解冻、额度调整、交易限额
        scenario_type = "G"

    # 没匹配到任何已知场景时：
    #   - 如果包含明确"我们还不支持"的业务关键词，抛异常（演示"不支持的场景"）；
    #   - 否则默认按"普通银行用户(A)"处理。
    if scenario_type is None:
        if any(k in text for k in ("贷款", "理财", "保险", "基金", "投资", "房贷", "车贷")):
            raise ScenarioError(
                "暂不支持的场景：当前只支持 普通用户(A)、购物支出增加(B)、"
                "疑似重复扣款(C)、余额不足(D)、周期性订阅(E)。"
            )
        scenario_type = "A"

    scenario_name = SCENARIO_TYPE_NAMES[scenario_type]
    params: Dict[str, Any] = {}
    # 保留解析到的金额，供适配层在"显式指定场景类型"时复用
    if amount_match:
        params["amount"] = round(increase_amount, 2)
    if scenario_type == "B":
        params["increase_amount"] = round(increase_amount, 2)
    elif scenario_type == "F":
        # 比赛要求"当月锁定 1000 元活期"，需求里没写金额时默认 1000 元
        params["monthly_activity_budget"] = round(increase_amount if amount_match and increase_amount > 0 else 1000.0, 2)

    return {
        "scenario_type": scenario_type,
        "scenario_name": scenario_name,
        "params": params,
        "requirements": build_requirements(scenario_type, params),
    }


def build_requirements(scenario_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """为每个场景生成"场景目标及预期条件"（对应 scenario_requirements 字段）。

    这里的 expected 是给人看的目标说明，程序化校验由 validator 按类型实现，
    且 validator 会基于实际流水重新计算，绝不凭空相信配置里的数字。
    """
    if scenario_type == "A":
        return {
            "goal": "生成一个普通银行用户，含用户信息、账户、初始余额，以及工资收入和日常消费流水。",
            "expected": {
                "has_user": True,
                "has_account": True,
                "has_income": True,
                "has_expense": True,
                "balance_non_negative": True,
            },
        }
    if scenario_type == "B":
        return {
            "goal": "生成连续两个月的购物消费，第二个月购物支出比第一个月增加指定金额（校验时按实际流水重算）。",
            "expected": {
                "two_consecutive_months": True,
                "shopping_increase": params.get("increase_amount", 800.0),
            },
        }
    if scenario_type == "C":
        return {
            "goal": "生成正常交易，并加入一组满足预设条件的疑似重复交易；保留全部原始交易，不删除任何交易。",
            "expected": {
                "has_normal_transactions": True,
                "has_duplicate_group": True,
                "duplicate_same_merchant_amount_category_date": True,
                "originals_preserved": True,
            },
        }
    if scenario_type == "D":
        return {
            "goal": "生成账户余额与一笔转账请求，使请求金额超过可用余额；交易应被拒绝，不允许出现负余额。",
            "expected": {
                "transfer_rejected": True,
                "no_negative_balance": True,
            },
        }
    if scenario_type == "E":
        return {
            "goal": "生成多个月份的固定周期扣款，保留商户、金额、日期与订阅类别信息。",
            "expected": {
                "multiple_months": True,
                "fixed_amount": True,
                "fixed_merchant": True,
                "has_subscription_category": True,
                "consecutive_months": True,
            },
        }
    if scenario_type == "F":
        return {
            "goal": (
                "模拟比赛中的跨场景联动：识别家庭成员生日，在生日当月锁定活动预算，"
                "并生成生日前 2 天的鲜花、蛋糕等订购活动日历。"
            ),
            "expected": {
                "family_birthday_in_lock_month": True,
                "locked_amount": params.get("monthly_activity_budget", 1000.0),
                "activity_calendar_coverage": True,
                "order_two_days_before": True,
                "calendar_within_locked_budget": True,
            },
        }
    if scenario_type == "G":
        return {
            "goal": (
                "模拟卡片管理：借记卡 + 信用卡、本期账单与未还金额，以及挂失/冻结/解冻、"
                "额度调整、交易限额等卡片事件；同时生成相关还款提醒。"
            ),
            "expected": {
                "has_debit_card": True,
                "has_credit_card": True,
                "credit_limit_matches_outstanding": True,
                "has_credit_card_bill": True,
                "has_card_events": True,
                "has_bill_due_reminder": True,
            },
        }
    return {"goal": "", "expected": {}}


# ============================================================================
# 3. 场景生成（临时实现，等 scenario_generator.py 完成后会被替换）
# ============================================================================
# 说明：以下 _gen_A ~ _gen_E 是"能跑起来的临时方案"，让 main.py 在没有
# scenario_generator.py 时也能生成场景。真正的生成逻辑后续应迁移到
# scenario_generator.py，main.py 只负责调用。数据模型目前用 dict，
# 将来 models.py 可用 dataclass 定义，但传给 main.py 的边界仍是 dict。

def _d(dt: datetime) -> str:
    """把 datetime 格式化成 YYYY-MM-DD 字符串。"""
    return dt.strftime("%Y-%m-%d")


def _rid(prefix: str) -> str:
    """生成带前缀的唯一 ID，例如 _rid("T") -> T3F2A9C1D4E5。

    这里用 random 而不是 uuid4，是为了让 set_seed() 之后 ID 也可复现。
    """
    return f"{prefix}{random.getrandbits(48):012X}"


def _random_name() -> str:
    """随机生成一个虚构中文姓名。"""
    family = random.choice(["王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴"])
    given = random.choice(["小明", "丽", "伟", "静", "强", "敏", "杰", "芳", "磊", "娜"])
    return family + given


def _random_id_number() -> str:
    """随机生成 18 位虚构身份证号（仅用于演示，不是真实号码）。"""
    area = random.choice(["110101", "310104", "440103", "510107", "330102"])
    birth = f"{random.randint(1975, 2002):04d}{random.randint(1, 12):02d}{random.randint(1, 28):02d}"
    seq = f"{random.randint(0, 999):03d}"
    return area + birth + seq + str(random.randint(0, 9))


def _random_phone() -> str:
    """随机生成 11 位虚构手机号。"""
    return "1" + random.choice(["3", "5", "7", "8", "9"]) + "".join(
        str(random.randint(0, 9)) for _ in range(9)
    )


def _days_in_month(year: int, month: int) -> int:
    """返回指定年月的天数。"""
    nxt = datetime(year, month, 28) + timedelta(days=4)
    return (nxt.replace(day=1) - timedelta(days=1)).day


def _shift_month(dt: datetime, delta: int) -> datetime:
    """返回 dt 所在月份平移 delta 个月后的同一天（日期越界时取当月最后一天）。"""
    idx = dt.year * 12 + (dt.month - 1) + delta
    year, month0 = divmod(idx, 12)
    month = month0 + 1
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def _split_amount(total: float, n: int) -> List[float]:
    """把总额 total（元）精确拆成 n 笔正数，总和精确等于 total。

    用"分"（整数）来拆分，避免浮点四舍五入造成总和不等于 total。
    """
    total_cents = int(round(total * 100))
    n = max(1, int(n))
    if total_cents < n:
        n = total_cents
    if n <= 1:
        return [total_cents / 100.0]
    # 在 1..total_cents-1 之间取 n-1 个切点，切成 n 段
    cuts = sorted(random.sample(range(1, total_cents), n - 1))
    bounds = [0] + cuts + [total_cents]
    parts = [bounds[i + 1] - bounds[i] for i in range(n)]
    return [p / 100.0 for p in parts]


def _t(
    account_id: str,
    date: str,
    amount: float,
    ttype: str,
    category: str,
    merchant: str = "",
    description: str = "",
    **extra: Any,
) -> Dict[str, Any]:
    """构造一笔交易 dict。金额统一非负，方向由 transaction_type 表达。"""
    txn: Dict[str, Any] = {
        "transaction_id": _rid("T"),
        "account_id": account_id,
        "date": date,
        "amount": round(float(amount), 2),  # 金额永远 >= 0
        "transaction_type": ttype,          # income/expense/transfer_in/transfer_out/refund
        "category": category,
        "merchant": merchant,
        "description": description,
        "status": "completed",              # 默认成功；被拒绝的交易会改成 rejected
    }
    txn.update(extra)
    return txn


def _net(txns: List[Dict[str, Any]]) -> float:
    """计算一批交易对余额的净影响（收入/转入/退款增加，支出/转出减少）。

    规则：
    - income / transfer_in / refund 使余额增加；
    - expense / transfer_out 使余额减少；
    - 状态不是 completed（如 rejected）的交易不影响余额。
    """
    total = 0.0
    for t in txns:
        if t.get("status") != "completed":
            continue
        if t["transaction_type"] in ("income", "transfer_in", "refund"):
            total += t["amount"]
        elif t["transaction_type"] in ("expense", "transfer_out"):
            total -= t["amount"]
    return round(total, 2)


def _make_user(user_id: str) -> Dict[str, Any]:
    """构造一个虚构用户。"""
    now = _now()
    return {
        "user_id": user_id,
        "name": _random_name(),
        "gender": random.choice(["男", "女"]),
        "id_number": _random_id_number(),
        "phone": _random_phone(),
        "email": f"{user_id.lower()}@example.com",
        "address": random.choice(
            ["北京市朝阳区", "上海市浦东新区", "广州市天河区", "成都市武侯区", "杭州市西湖区"]
        ),
        "occupation": random.choice(["软件工程师", "教师", "医生", "设计师", "会计", "市场专员"]),
        "monthly_income": round(random.uniform(8000, 25000), 2),
        "registration_date": _d(now - timedelta(days=random.randint(300, 2000))),
    }


def _make_account(account_id: str, user_id: str, initial_balance: float, balance: float) -> Dict[str, Any]:
    """构造一个账户。initial_balance 为期初余额，balance 为期末余额。"""
    now = _now()
    return {
        "account_id": account_id,
        "user_id": user_id,
        "account_type": "储蓄卡",
        "account_number": "6222" + "".join(str(random.randint(0, 9)) for _ in range(15)),
        "currency": "CNY",
        "initial_balance": round(float(initial_balance), 2),
        "balance": round(float(balance), 2),
        "status": "正常",
        "opened_date": _d(now - timedelta(days=random.randint(300, 2000))),
    }


def _assemble(config: Dict[str, Any], user: Dict[str, Any], accounts: List[Dict[str, Any]],
              transactions: List[Dict[str, Any]], **extras: Any) -> Dict[str, Any]:
    """把各部分组成完整的场景 dict（符合统一数据格式）。

    extras 用来附加卡片、家庭、日历、洞察等区块，不改变原有字段。
    """
    scenario = {
        "scenario_id": config["scenario_id"],
        "scenario_name": config["scenario_name"],
        "scenario_type": config["scenario_type"],
        "created_at": _now().isoformat(timespec="seconds"),
        "user": user,
        "accounts": accounts,
        "transactions": transactions,
        "scenario_requirements": config["requirements"],
    }
    scenario.update(extras)
    return scenario


# ---------------------------------------------------------------------------
# 3.1 卡片、日历与智能洞察（所有场景共享的"生活层"）
# ---------------------------------------------------------------------------

CREDIT_CATEGORIES = ["购物", "餐饮", "交通", "娱乐", "旅行", "日用"]


def _make_credit_card_items(card: Dict[str, Any], now: datetime) -> List[Dict[str, Any]]:
    """生成本期信用卡消费（独立于借记卡流水，不影响存款账户余额）。"""
    cycle_start, statement_date, _ = banking_domain.statement_period(card, now)
    span = max(0, (statement_date - cycle_start).days)
    items: List[Dict[str, Any]] = []

    for _ in range(random.randint(3, 6)):
        item_date = cycle_start + timedelta(days=random.randint(0, span))
        if item_date > now.date():
            item_date = now.date()
        items.append({
            "transaction_id": _rid("CT"),
            "card_id": card["card_id"],
            "date": _d(item_date),
            "amount": round(random.uniform(30, 900), 2),
            "transaction_type": "expense",
            "category": random.choice(CREDIT_CATEGORIES),
            "merchant": random.choice(["某电商平台", "某餐厅", "某旅行平台", "某商场", "某超市"]),
            "description": "信用卡消费",
            "status": "completed",
        })

    items.sort(key=lambda item: item["date"])
    return items


def _choose_paid_amount(items: List[Dict[str, Any]]) -> float:
    """决定本期已还金额：0（未还）/ 部分还款 / 全额还款。"""
    total = round(sum(item["amount"] for item in items), 2)
    roll = random.random()
    if roll < 0.35:
        return 0.0
    if roll < 0.7:
        return round(total * random.uniform(0.3, 0.8), 2)
    return total


def _detect_salary_day(transactions: List[Dict[str, Any]]) -> Optional[int]:
    """从工资流水里找出每月发薪日，供日历生成"工资日"提醒。"""
    salaries = [
        t for t in transactions
        if t.get("transaction_type") == "income"
        and t.get("category") == "工资"
        and t.get("status", "completed") == "completed"
        and isinstance(t.get("date"), str) and len(t["date"]) == 10
    ]
    if not salaries:
        return None
    latest = max(salaries, key=lambda t: t["date"])
    return int(latest["date"][8:10])


def _make_insight(
    insight_type: str,
    severity: str,
    title: str,
    event_date: str,
    evidence_ids: Optional[List[str]] = None,
    *,
    related_event_id: Optional[str] = None,
    related_card_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造一条"智能检测"标签（给分析 Agent 做评测答案用）。"""
    return {
        "insight_id": _rid("INS"),
        "insight_type": insight_type,
        "severity": severity,
        "title": title,
        "date": event_date,
        "evidence_transaction_ids": list(evidence_ids or []),
        "related_event_id": related_event_id,
        "related_card_id": related_card_id,
        "details": details or {},
    }


def _find_event(calendar_events: List[Dict[str, Any]], **match: Any) -> Optional[Dict[str, Any]]:
    """按字段匹配日历事件（用于把洞察和日历条目关联起来）。"""
    for event in calendar_events:
        if all(event.get(key) == value for key, value in match.items()):
            return event
    return None


def _build_insights(scenario: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从已生成的数据推导"智能检测"结果（带证据交易 ID）。

    注意：这是**生成时已知的标注答案**，用来评估分析 Agent 的识别准确率；
    真实运行时分析 Agent 应该只看流水自己算出来，不能直接读这个字段。
    """
    insights: List[Dict[str, Any]] = []
    transactions = scenario.get("transactions", [])
    calendar_events = scenario.get("calendar_events", [])

    # 1) 识别工资
    salaries = [
        t for t in transactions
        if t.get("transaction_type") == "income" and t.get("category") == "工资"
        and t.get("status", "completed") == "completed"
    ]
    if salaries:
        latest = max(salaries, key=lambda t: t["date"])
        insights.append(_make_insight(
            "salary_detected", "low", "识别到工资收入", latest["date"],
            [latest["transaction_id"]],
            details={"merchant": latest.get("merchant"), "cycle": "monthly"},
        ))

    # 2) 疑似重复扣款（场景 C）
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for transaction in transactions:
        group_id = transaction.get("duplicate_group_id")
        if group_id:
            groups.setdefault(group_id, []).append(transaction)
    for group_id, members in groups.items():
        if len(members) < 2:
            continue
        insights.append(_make_insight(
            "duplicate_charge", "high", "发现疑似重复扣款",
            max(member["date"] for member in members),
            [member["transaction_id"] for member in members],
            details={
                "group_id": group_id,
                "merchant": members[0].get("merchant"),
                "count": len(members),
            },
        ))

    # 3) 信用卡还款临近（已过还款日则提示逾期）
    bill = scenario.get("credit_card_bill")
    if bill and bill.get("outstanding_amount", 0) > 0:
        card_id = bill.get("card_id")
        due_event = _find_event(calendar_events, event_type="bill_due", related_card_id=card_id)
        try:
            overdue = datetime.strptime(bill["due_date"], "%Y-%m-%d").date() < _now().date()
        except (KeyError, TypeError, ValueError):
            overdue = False
        insights.append(_make_insight(
            "upcoming_bill", "high",
            "信用卡账单已逾期" if overdue else "信用卡账单待还款",
            bill["due_date"],
            [],
            related_event_id=due_event["event_id"] if due_event else None,
            related_card_id=card_id,
            details={
                "bill_status": bill.get("status"),
                "overdue": overdue,
                "with_minimum_payment": True,
            },
        ))

    # 4) 订阅即将续费
    for subscription in scenario.get("subscriptions", []) or []:
        if subscription.get("status") != "active":
            continue
        related_event = _find_event(
            calendar_events,
            event_type="subscription_renewal",
            related_subscription_id=subscription.get("subscription_id"),
        )
        evidence = [
            t for t in transactions
            if t.get("category") == "订阅" and t.get("merchant") == subscription.get("merchant")
        ]
        latest = max(evidence, key=lambda t: t["date"]) if evidence else None
        insights.append(_make_insight(
            "subscription_renewal", "medium", f"{subscription.get('merchant')}即将续费",
            subscription.get("next_charge_date", ""),
            [latest["transaction_id"]] if latest else [],
            related_event_id=related_event["event_id"] if related_event else None,
            details={"merchant": subscription.get("merchant"), "cycle": subscription.get("cycle")},
        ))

    # 5) 生日与预算锁定（场景 F / 有家庭信息的场景）
    today = _now().date()
    for member in scenario.get("family", []) or []:
        related_event = _find_event(
            calendar_events, event_type="birthday", related_member_id=member.get("member_id")
        )
        event_date = member.get("birthday", "")
        try:
            days_until = (datetime.strptime(event_date, "%Y-%m-%d").date() - today).days
        except (TypeError, ValueError):
            days_until = 0
        # 越临近越紧急：30 天内高优先级，90 天内中，其余低
        severity = "high" if days_until <= 30 else ("medium" if days_until <= 90 else "low")
        relation = member.get("relation", "家人")
        title = f"{relation}生日临近" if days_until <= 30 else f"{relation}生日提醒"
        insights.append(_make_insight(
            "birthday_upcoming", severity, title,
            event_date,
            [],
            related_event_id=related_event["event_id"] if related_event else None,
            details={
                "relation": relation,
                "age_turning": member.get("age_turning"),
                "days_until": days_until,
            },
        ))

    budget = scenario.get("budget")
    if budget and budget.get("locked_amount"):
        related_event = _find_event(calendar_events, event_type="budget_lock")
        insights.append(_make_insight(
            "budget_lock", "medium", "生日活动预算已锁定",
            budget.get("lock_month", "") + "-01" if budget.get("lock_month") else "",
            [],
            related_event_id=related_event["event_id"] if related_event else None,
            details={"locked": True, "calendar_entries": len(scenario.get("activity_calendar", []))},
        ))

    # 6) 被拒绝/失败的转账
    for transaction in transactions:
        if transaction.get("status") != "rejected" and transaction.get("expected_result") != "rejected":
            continue
        insights.append(_make_insight(
            "failed_transfer", "high", "转账请求被拒绝",
            transaction.get("date", ""),
            [transaction["transaction_id"]],
            details={"reason": transaction.get("description", "")},
        ))

    # 7) 异常消费：单笔超过平均支出的 4 倍且不低于 1000 元
    expenses = [
        t for t in transactions
        if t.get("transaction_type") == "expense" and t.get("status", "completed") == "completed"
    ]
    if len(expenses) >= 3:
        average = sum(t["amount"] for t in expenses) / len(expenses)
        outliers = [t for t in expenses if t["amount"] >= 1000 and t["amount"] > average * 4]
        for outlier in outliers[:2]:
            insights.append(_make_insight(
                "unusual_spending", "medium", "发现异常大额消费",
                outlier["date"],
                [outlier["transaction_id"]],
                details={"merchant": outlier.get("merchant"), "category": outlier.get("category")},
            ))

    insights.sort(key=lambda item: (item["date"], item["insight_id"]))
    return insights


def _decorate_scenario(
    scenario: Dict[str, Any],
    now: datetime,
    account: Dict[str, Any],
    *,
    family: Optional[List[Dict[str, Any]]] = None,
    subscriptions: Optional[List[Dict[str, Any]]] = None,
    budget: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """给任意场景补上卡片、信用卡账单、日历提醒和智能检测标签。"""
    user_id = scenario["user"]["user_id"]
    debit, credit = banking_domain.make_cards(user_id, account["account_id"], now)
    items = _make_credit_card_items(credit, now)
    bill = banking_domain.make_credit_card_bill(credit, items, _choose_paid_amount(items), now)

    scenario["cards"] = [debit, credit]
    scenario["credit_card_bill"] = bill
    if family is not None:
        scenario["family"] = family
    if subscriptions is not None:
        scenario["subscriptions"] = subscriptions
    if budget is not None:
        scenario["budget"] = budget

    scenario["calendar_events"] = banking_domain.make_calendar_events(
        now,
        scenario.get("family", []),
        [credit],
        subscriptions=subscriptions,
        salary_day=_detect_salary_day(scenario["transactions"]),
        budget=budget,
    )
    scenario["expected_insights"] = _build_insights(scenario)
    return scenario


def _gen_A(config: Dict[str, Any]) -> Dict[str, Any]:
    """场景 A：普通银行用户。"""
    now = _now()
    user_id = _rid("U")
    account_id = _rid("ACC")
    initial_balance = round(random.uniform(3000, 15000), 2)

    txns: List[Dict[str, Any]] = []
    # 一笔工资收入（本月 1 号）
    txns.append(_t(
        account_id, _d(now.replace(day=1)),
        round(random.uniform(8000, 25000), 2), "income", "工资",
        merchant="示例科技有限公司", description="月度工资收入",
    ))
    # 近 30 天随机 8~12 笔日常消费
    cats = ["餐饮", "交通", "购物", "娱乐", "日用", "通讯"]
    for _ in range(random.randint(8, 12)):
        txns.append(_t(
            account_id, _d(now - timedelta(days=random.randint(0, 29))),
            round(random.uniform(15, 500), 2), "expense", random.choice(cats),
            merchant=random.choice(["某超市", "某餐厅", "某咖啡店", "某加油站", "某电影院"]),
        ))

    txns.sort(key=lambda t: t["date"])
    balance = round(initial_balance + _net(txns), 2)
    account = _make_account(account_id, user_id, initial_balance, balance)
    scenario = _assemble(config, _make_user(user_id), [account], txns)
    return _decorate_scenario(scenario, now, account, family=banking_domain.make_family(now))


def _gen_B(config: Dict[str, Any]) -> Dict[str, Any]:
    """场景 B：购物支出增加。第二个月购物总额 = 第一个月购物总额 + increase_amount。"""
    now = _now()
    increase = float(config["params"].get("increase_amount", 800.0))
    user_id = _rid("U")
    account_id = _rid("ACC")

    this_month = now.replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)

    base1 = round(random.uniform(1500, 4000), 2)          # 上个月购物总额
    base2 = round(base1 + increase, 2)                    # 本月购物总额（保证增加额精确）

    txns: List[Dict[str, Any]] = []
    merchants = ["天天购物中心", "华联超市", "宜家家居", "某电商平台"]
    amounts1 = _split_amount(base1, 4)
    amounts2 = _split_amount(base2, 4)

    for i, amt in enumerate(amounts1):
        day = random.randint(1, _days_in_month(last_month.year, last_month.month))
        txns.append(_t(account_id, _d(last_month.replace(day=day)), amt, "expense", "购物",
                       merchant=merchants[i % 4], description="购物消费"))
    for i, amt in enumerate(amounts2):
        day = random.randint(1, _days_in_month(this_month.year, this_month.month))
        txns.append(_t(account_id, _d(this_month.replace(day=day)), amt, "expense", "购物",
                       merchant=merchants[i % 4], description="购物消费"))

    # 加一点非购物交易让场景更真实（工资 + 一笔餐饮）
    txns.append(_t(account_id, _d(this_month.replace(day=1)),
                   round(random.uniform(8000, 20000), 2), "income", "工资",
                   merchant="示例科技有限公司", description="月度工资收入"))
    txns.append(_t(account_id, _d(this_month.replace(day=3)),
                   round(random.uniform(20, 80), 2), "expense", "餐饮",
                   merchant="某餐厅", description="午餐"))

    txns.sort(key=lambda t: t["date"])
    initial_balance = round(random.uniform(5000, 15000), 2)
    balance = round(initial_balance + _net(txns), 2)
    account = _make_account(account_id, user_id, initial_balance, balance)
    scenario = _assemble(config, _make_user(user_id), [account], txns)
    return _decorate_scenario(scenario, now, account, family=banking_domain.make_family(now))


def _gen_C(config: Dict[str, Any]) -> Dict[str, Any]:
    """场景 C：疑似重复扣款。正常交易 + 一组同商户/同金额/同类别/同日期且时间接近的疑似重复交易。"""
    now = _now()
    user_id = _rid("U")
    account_id = _rid("ACC")

    txns: List[Dict[str, Any]] = []
    # 正常交易：工资 + 几笔日常消费
    txns.append(_t(account_id, _d(now - timedelta(days=30)),
                   round(random.uniform(8000, 20000), 2), "income", "工资",
                   merchant="示例科技有限公司", description="月度工资收入"))
    for _ in range(random.randint(4, 7)):
        txns.append(_t(account_id, _d(now - timedelta(days=random.randint(1, 25))),
                       round(random.uniform(20, 400), 2), "expense",
                       random.choice(["餐饮", "交通", "购物", "娱乐", "日用"]),
                       merchant=random.choice(["某超市", "某餐厅", "某咖啡店", "某加油站"])))

    # 疑似重复扣款组：同商户、同金额、同类别、同日期，时间相差 2 分钟
    dup_amount = round(random.uniform(100, 600), 2)
    dup_merchant = "某电商平台"
    dup_day = now - timedelta(days=random.randint(1, 5))
    group_id = _rid("DUP")

    original = _t(account_id, _d(dup_day), dup_amount, "expense", "购物",
                  merchant=dup_merchant, description="线上购物支付",
                  is_suspicious=True, duplicate_group_id=group_id, time="10:00:00")
    duplicate = _t(account_id, _d(dup_day), dup_amount, "expense", "购物",
                   merchant=dup_merchant, description="疑似重复扣款",
                   is_suspicious=True, duplicate_group_id=group_id, time="10:02:00")
    # 双向关联，方便主 Agent 追踪"谁和谁重复"
    original["related_transaction_id"] = duplicate["transaction_id"]
    duplicate["related_transaction_id"] = original["transaction_id"]
    txns.extend([original, duplicate])  # 保留全部交易，不删除任何一笔

    txns.sort(key=lambda t: t["date"])
    initial_balance = round(random.uniform(5000, 20000), 2)
    balance = round(initial_balance + _net(txns), 2)
    account = _make_account(account_id, user_id, initial_balance, balance)
    scenario = _assemble(config, _make_user(user_id), [account], txns)
    return _decorate_scenario(scenario, now, account, family=banking_domain.make_family(now))


def _gen_D(config: Dict[str, Any]) -> Dict[str, Any]:
    """场景 D：余额不足。转账请求金额 > 可用余额，交易被拒绝，余额不为负。"""
    now = _now()
    user_id = _rid("U")
    account_id = _rid("ACC")

    txns: List[Dict[str, Any]] = []
    txns.append(_t(account_id, _d(now - timedelta(days=15)),
                   round(random.uniform(8000, 15000), 2), "income", "工资",
                   merchant="示例科技有限公司", description="月度工资收入"))
    txns.append(_t(account_id, _d(now - timedelta(days=10)),
                   round(random.uniform(500, 3000), 2), "expense", "购物",
                   merchant="某购物中心", description="购物消费"))
    txns.append(_t(account_id, _d(now - timedelta(days=5)),
                   round(random.uniform(100, 800), 2), "expense", "餐饮",
                   merchant="某餐厅", description="聚餐"))

    # 期初余额 + 已完成流水 = 当前可用余额
    initial_balance = round(random.uniform(500, 2000), 2)
    available = round(initial_balance + _net(txns), 2)

    # 转账请求金额超过可用余额，状态为 rejected（被拒绝），不影响余额
    transfer_amount = round(available + random.uniform(200, 3000), 2)
    txns.append(_t(account_id, _d(now), transfer_amount, "transfer_out", "转账",
                   merchant="收款人-张三",
                   description="转账请求：金额超过可用余额，被银行拒绝",
                   status="rejected", expected_result="rejected"))

    txns.sort(key=lambda t: t["date"])
    balance = round(initial_balance + _net(txns), 2)  # 被拒绝交易不计入，余额不变
    account = _make_account(account_id, user_id, initial_balance, balance)
    scenario = _assemble(config, _make_user(user_id), [account], txns)
    return _decorate_scenario(scenario, now, account, family=banking_domain.make_family(now))


def _gen_E(config: Dict[str, Any]) -> Dict[str, Any]:
    """场景 E：周期性订阅。多个月份的固定周期扣款，保留商户/金额/日期/订阅类别。"""
    now = _now()
    user_id = _rid("U")
    account_id = _rid("ACC")

    sub_type, merchant = random.choice([
        ("视频会员", "某视频平台"),
        ("音乐会员", "某音乐平台"),
        ("云存储会员", "某云盘服务"),
        ("新闻会员", "某资讯平台"),
    ])
    amount = round(random.choice([15.0, 19.9, 25.0, 30.0]), 2)
    day_of_month = random.randint(1, 20)
    months = random.randint(4, 8)

    txns: List[Dict[str, Any]] = []
    this_month = now.replace(day=1)
    for i in range(months):
        m = _shift_month(this_month, -i)
        # 每月同一天扣款；月份天数不足时取当月最后一天
        d = m.replace(day=min(day_of_month, _days_in_month(m.year, m.month)))
        txns.append(_t(account_id, _d(d), amount, "expense", "订阅",
                       merchant=merchant,
                       description=f"{sub_type} 月度订阅扣款",
                       subscription_type=sub_type, subscription_cycle="monthly",
                       recurring=True))
        # 每月也发一次工资，保证余额充足
        txns.append(_t(account_id, _d(m.replace(day=1)),
                       round(random.uniform(8000, 20000), 2), "income", "工资",
                       merchant="示例科技有限公司", description="月度工资收入"))

    txns.sort(key=lambda t: t["date"])
    initial_balance = round(random.uniform(2000, 6000), 2)
    balance = round(initial_balance + _net(txns), 2)
    account = _make_account(account_id, user_id, initial_balance, balance)
    scenario = _assemble(config, _make_user(user_id), [account], txns)

    # 订阅区块：给主 Agent 提供"下次扣费日/状态"，支撑续费提醒与一键取消
    charges = [t for t in txns if t.get("category") == "订阅"]
    last_charge = max(charges, key=lambda t: t["date"])
    last_date = datetime.strptime(last_charge["date"], "%Y-%m-%d").date()
    next_charge = last_date if last_date > now.date() else banking_domain.shift_month(last_date, 1)
    subscriptions = [{
        "subscription_id": _rid("SUB"),
        "merchant": merchant,
        "amount": amount,
        "cycle": "monthly",
        "category": "订阅",
        "subscription_type": sub_type,
        "last_charge_date": last_charge["date"],
        "next_charge_date": _d(next_charge),
        "status": "active",
    }]

    return _decorate_scenario(
        scenario, now, account,
        family=banking_domain.make_family(now),
        subscriptions=subscriptions,
    )


def _gen_F(config: Dict[str, Any]) -> Dict[str, Any]:
    """场景 F：家庭生日跨场景联动（对应比赛"跨场景联动"）。

    生成内容：
    - family：一位家庭成员及其生日（生日落在当月）；
    - budget：当月活动预算与锁定金额（比赛示例为 1000 元）；
    - activity_calendar：生日前 2 天订购鲜花、蛋糕，以及可选的晚餐/礼物；
    - transactions：正常工资与日常消费流水（保证账户可对账）。

    金额全部用"分"计算，保证日历合计不超过锁定金额。
    """
    now = _now()
    user_id = _rid("U")
    account_id = _rid("ACC")

    budget = float(config.get("params", {}).get("monthly_activity_budget", 1000.0))
    if not math.isfinite(budget) or budget <= 0:
        budget = 1000.0

    # 生日取未来 3~25 天内，保证"生日前 2 天"还没过去，且落在同一个锁定月份
    family = banking_domain.make_family(now, count=1, window_days=25, relations=["配偶"])
    member_id = family[0]["member_id"]
    birthday = datetime.strptime(family[0]["birthday"], "%Y-%m-%d")
    order_date = birthday - timedelta(days=2)
    lock_month = birthday.strftime("%Y-%m")

    # 用"分"分配预算：鲜花、蛋糕固定安排，晚餐/礼物视剩余预算决定
    total_cents = int(round(budget * 100))
    flower_cents = max(1, int(total_cents * random.uniform(0.20, 0.28)))
    cake_cents = max(1, int(total_cents * random.uniform(0.18, 0.26)))
    remaining_cents = total_cents - flower_cents - cake_cents

    calendar: List[Dict[str, Any]] = [
        {
            "event_id": _rid("EVT"),
            "date": _d(order_date),
            "title": "预订生日鲜花",
            "category": "鲜花",
            "budget": round(flower_cents / 100.0, 2),
            "status": "planned",
            "related_member_id": member_id,
            "auto_order": True,
        },
        {
            "event_id": _rid("EVT"),
            "date": _d(order_date),
            "title": "预订生日蛋糕",
            "category": "蛋糕",
            "budget": round(cake_cents / 100.0, 2),
            "status": "planned",
            "related_member_id": member_id,
            "auto_order": True,
        },
    ]

    extras = [("生日晚餐", "安排生日晚餐", _d(birthday)),
              ("生日礼物", "购买生日礼物", _d(order_date))]
    for category, title, event_date in extras:
        if remaining_cents <= 0:
            break
        part_cents = int(remaining_cents * random.uniform(0.35, 0.6))
        if part_cents <= 0:
            break
        calendar.append({
            "event_id": _rid("EVT"),
            "date": event_date,
            "title": title,
            "category": category,
            "budget": round(part_cents / 100.0, 2),
            "status": "planned",
            "related_member_id": member_id,
            "auto_order": False,
        })
        remaining_cents -= part_cents

    calendar.sort(key=lambda entry: entry["date"])

    # 正常流水：工资 + 日常消费（让主 Agent 还能做账单分析）
    txns: List[Dict[str, Any]] = [
        _t(account_id, _d(now.replace(day=1)), round(random.uniform(8000, 25000), 2),
           "income", "工资", merchant="示例科技有限公司", description="月度工资收入"),
    ]
    for _ in range(random.randint(8, 12)):
        txns.append(_t(
            account_id, _d(now - timedelta(days=random.randint(0, 29))),
            round(random.uniform(15, 500), 2), "expense",
            random.choice(["餐饮", "交通", "购物", "娱乐", "日用", "通讯"]),
            merchant=random.choice(["某超市", "某餐厅", "某咖啡店", "某加油站", "某电影院"]),
        ))

    txns.sort(key=lambda t: t["date"])
    # 期初余额至少覆盖锁定预算，保证"锁定的是活期可用资金"这一语义成立
    initial_balance = round(random.uniform(3000, 15000) + budget, 2)
    balance = round(initial_balance + _net(txns), 2)

    account = _make_account(account_id, user_id, initial_balance, balance)
    scenario = _assemble(config, _make_user(user_id), [account], txns)
    scenario["activity_calendar"] = calendar
    budget_info = {
        "monthly_activity_budget": round(budget, 2),
        "locked_amount": round(budget, 2),
        "currency": "CNY",
        "lock_month": lock_month,
        "note": "生日当月锁定活动预算，日历合计不超过锁定金额",
    }
    return _decorate_scenario(scenario, now, account, family=family, budget=budget_info)


def _card_event(
    card_id: str,
    event_type: str,
    event_date: datetime,
    before: Dict[str, Any],
    after: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    """构造一条卡片事件（挂失、冻结、额度调整、限额设置、补卡）。"""
    return {
        "event_id": _rid("CEV"),
        "card_id": card_id,
        "date": _d(event_date),
        "event_type": event_type,
        "status": "completed",
        "before": before,
        "after": after,
        "reason": reason,
    }


def _apply_card_story(scenario: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """给 G 场景加一段真实的卡片管理剧情，并把卡片状态改到与事件一致。"""
    credit = next(card for card in scenario["cards"] if card["card_type"] == "credit")
    event_day = now - timedelta(days=random.randint(0, 5))
    events: List[Dict[str, Any]] = []

    story = random.choice([
        "limit_adjusted", "transaction_limit_set", "frozen_then_unfrozen", "lost_then_replaced",
    ])

    if story == "limit_adjusted":
        old_limit = float(credit["credit_limit"])
        new_limit = min(old_limit + random.choice([5000.0, 10000.0, 20000.0]), 100000.0)
        credit["credit_limit"] = round(new_limit, 2)
        credit["available_credit"] = round(new_limit - float(credit["used_credit"]), 2)
        events.append(_card_event(
            credit["card_id"], "limit_adjusted", event_day,
            {"credit_limit": old_limit}, {"credit_limit": round(new_limit, 2)},
            "消费与还款记录良好，银行主动调整额度",
        ))

    elif story == "transaction_limit_set":
        old_limit = dict(credit["transaction_limit"])
        new_limit = {"daily": 10000.0, "single": 5000.0}
        credit["transaction_limit"] = new_limit
        events.append(_card_event(
            credit["card_id"], "transaction_limit_set", event_day,
            {"transaction_limit": old_limit}, {"transaction_limit": dict(new_limit)},
            "用户主动下调交易限额，降低盗刷风险",
        ))

    elif story == "frozen_then_unfrozen":
        credit["status"] = "frozen"
        events.append(_card_event(
            credit["card_id"], "card_frozen", event_day - timedelta(days=2),
            {"status": "active"}, {"status": "frozen"},
            "怀疑卡片信息泄露，临时冻结",
        ))
        credit["status"] = "active"
        events.append(_card_event(
            credit["card_id"], "card_unfrozen", event_day,
            {"status": "frozen"}, {"status": "active"},
            "核实无异常后解冻",
        ))

    else:  # lost_then_replaced
        old_number = credit["card_number_masked"]
        credit["status"] = "lost"
        events.append(_card_event(
            credit["card_id"], "card_lost", event_day - timedelta(days=1),
            {"status": "active"}, {"status": "lost"},
            "卡片遗失，用户申请挂失",
        ))
        new_number = banking_domain.masked_card_number("6225")
        credit["card_number_masked"] = new_number
        credit["status"] = "active"
        events.append(_card_event(
            credit["card_id"], "card_replaced", event_day,
            {"status": "lost", "card_number_masked": old_number},
            {"status": "active", "card_number_masked": new_number},
            "挂失后补发新卡，卡号变更",
        ))

    events.sort(key=lambda event: event["date"])
    scenario["card_events"] = events
    return scenario


def _gen_G(config: Dict[str, Any]) -> Dict[str, Any]:
    """场景 G：信用卡与卡片管理（对应比赛"卡片管理"）。

    生成内容：借记卡 + 信用卡、本期信用卡账单（消费明细/最低还款/未还金额）、
    一段卡片事件（提额 / 限额 / 冻结解冻 / 挂失补卡），以及还款日提醒。
    """
    now = _now()
    user_id = _rid("U")
    account_id = _rid("ACC")

    txns: List[Dict[str, Any]] = [
        _t(account_id, _d(now.replace(day=1)), round(random.uniform(8000, 25000), 2),
           "income", "工资", merchant="示例科技有限公司", description="月度工资收入"),
    ]
    for _ in range(random.randint(6, 10)):
        txns.append(_t(
            account_id, _d(now - timedelta(days=random.randint(0, 29))),
            round(random.uniform(20, 600), 2), "expense",
            random.choice(["餐饮", "交通", "购物", "娱乐", "日用"]),
            merchant=random.choice(["某超市", "某餐厅", "某咖啡店", "某加油站"]),
            description="借记卡消费",
        ))

    txns.sort(key=lambda t: t["date"])
    initial_balance = round(random.uniform(5000, 20000), 2)
    balance = round(initial_balance + _net(txns), 2)
    account = _make_account(account_id, user_id, initial_balance, balance)
    scenario = _assemble(config, _make_user(user_id), [account], txns)
    _decorate_scenario(scenario, now, account, family=banking_domain.make_family(now))
    return _apply_card_story(scenario, now)


def generate_scenario_fallback(config: Dict[str, Any]) -> Dict[str, Any]:
    """临时生成器：按场景类型分发到对应的生成函数。"""
    dispatch = {
        "A": _gen_A,
        "B": _gen_B,
        "C": _gen_C,
        "D": _gen_D,
        "E": _gen_E,
        "F": _gen_F,
        "G": _gen_G,
    }
    if config["scenario_type"] not in dispatch:
        raise ScenarioError(f"不支持的场景类型：{config['scenario_type']}")
    return dispatch[config["scenario_type"]](config)


# ============================================================================
# 4. 场景校验（临时实现，等 validator.py 完成后会被替换）
# ============================================================================

def _months_are_consecutive(ym1: str, ym2: str) -> bool:
    """判断两个 "YYYY-MM" 是否是相邻的连续月份。"""
    y1, m1 = (int(x) for x in ym1.split("-"))
    y2, m2 = (int(x) for x in ym2.split("-"))
    return (y2 == y1 and m2 == m1 + 1) or (y2 == y1 + 1 and m1 == 12 and m2 == 1)


def validate_scenario_fallback(scenario: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """临时校验器：对生成结果做结构与场景目标校验，返回 (是否通过, 消息列表)。

    所有场景目标都基于实际流水重新计算，绝不凭空相信配置里的数字。
    """
    errors: List[str] = []
    warnings: List[str] = []

    # ---- 1. 顶层结构与交易字段校验 ----
    for field in ("scenario_id", "scenario_name", "user", "accounts", "transactions", "scenario_requirements"):
        if not scenario.get(field):
            errors.append(f"缺少顶层字段：{field}")

    txns: List[Dict[str, Any]] = scenario.get("transactions", [])
    if not txns:
        errors.append("交易流水为空")
    if not scenario.get("accounts"):
        errors.append("账户列表为空")

    for i, t in enumerate(txns):
        for field in ("transaction_id", "date", "amount", "transaction_type", "category", "account_id"):
            if t.get(field) in (None, ""):
                errors.append(f"第 {i + 1} 笔交易缺少字段：{field}")
                break
        if "amount" in t and t["amount"] < 0:
            errors.append(f"交易 {t.get('transaction_id')} 金额为负（金额应统一非负）")
        if t.get("transaction_type") not in VALID_TRANSACTION_TYPES:
            errors.append(f"交易 {t.get('transaction_id')} 类型非法：{t.get('transaction_type')}")

    # ---- 2. 账户引用与余额一致性校验 ----
    account_ids = {a.get("account_id") for a in scenario.get("accounts", [])}
    for t in txns:
        if t.get("account_id") and t["account_id"] not in account_ids:
            errors.append(f"交易 {t.get('transaction_id')} 引用了不存在的账户 {t['account_id']}")

    for a in scenario.get("accounts", []):
        acct_txns = [t for t in txns if t.get("account_id") == a.get("account_id")]
        expected = round(a.get("initial_balance", 0.0) + _net(acct_txns), 2)
        if abs(expected - a.get("balance", 0.0)) > 0.01:
            errors.append(
                f"账户 {a.get('account_id')} 余额不一致：记录 {a.get('balance')}，实际计算 {expected}"
            )
        if a.get("balance", 0.0) < 0:
            errors.append(f"账户 {a.get('account_id')} 出现负余额")

    # ---- 3. 场景目标校验（按类型，基于实际流水重算） ----
    stype = scenario.get("scenario_type", config.get("scenario_type"))

    if stype == "A":
        types = {t["transaction_type"] for t in txns}
        if "income" not in types:
            errors.append("场景A：缺少收入流水（工资）")
        if "expense" not in types:
            errors.append("场景A：缺少日常消费支出流水")

    elif stype == "B":
        increase = float(config.get("params", {}).get("increase_amount", 800.0))
        monthly: Dict[str, float] = defaultdict(float)
        for t in txns:
            if t.get("category") == "购物" and t.get("transaction_type") == "expense" \
                    and t.get("status", "completed") == "completed":
                monthly[t["date"][:7]] += t["amount"]  # 按 "YYYY-MM" 汇总
        months = sorted(monthly.keys())
        if len(months) < 2:
            errors.append("场景B：购物消费没有覆盖连续两个月")
        else:
            m1, m2 = months[-2], months[-1]
            if not _months_are_consecutive(m1, m2):
                errors.append(f"场景B：购物消费的两个月 {m1} 和 {m2} 不连续")
            diff = round(monthly[m2] - monthly[m1], 2)
            if abs(diff - increase) > 0.01:
                errors.append(
                    f"场景B：第二个月购物支出比第一个月增加 {diff} 元，"
                    f"不等于要求的 {increase} 元"
                )

    elif stype == "C":
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for t in txns:
            gid = t.get("duplicate_group_id")
            if gid:
                groups[gid].append(t)
        if not groups:
            errors.append("场景C：未找到疑似重复扣款组")
        else:
            for gid, members in groups.items():
                if len(members) < 2:
                    errors.append(f"场景C：重复组 {gid} 成员不足 2 笔")
                    continue
                amounts = {m["amount"] for m in members}
                merchants = {m.get("merchant") for m in members}
                cats = {m.get("category") for m in members}
                dates = {m.get("date") for m in members}
                if len(amounts) != 1 or len(merchants) != 1 or len(cats) != 1 or len(dates) != 1:
                    errors.append(f"场景C：重复组 {gid} 的金额/商户/类别/日期不一致，不满足重复扣款条件")
        if not any(not t.get("is_suspicious") for t in txns):
            errors.append("场景C：未保留原始正常交易")

    elif stype == "D":
        rejected = [t for t in txns
                    if t.get("status") == "rejected" or t.get("expected_result") == "rejected"]
        if not rejected:
            errors.append("场景D：缺少被拒绝的转账请求")
        else:
            for t in rejected:
                acct = next((a for a in scenario.get("accounts", [])
                             if a.get("account_id") == t.get("account_id")), None)
                if acct is None:
                    continue
                if t["amount"] <= acct["balance"]:
                    errors.append(
                        f"场景D：转账请求 {t.get('transaction_id')} 金额 {t['amount']} "
                        f"未超过可用余额 {acct['balance']}"
                    )

    elif stype == "E":
        subs = [t for t in txns if t.get("category") == "订阅" or t.get("recurring")]
        if len(subs) < 2:
            errors.append("场景E：周期订阅扣款不足 2 期")
        else:
            amounts = {t["amount"] for t in subs}
            merchants = {t.get("merchant") for t in subs}
            cats = {t.get("category") for t in subs}
            if len(amounts) != 1:
                errors.append("场景E：订阅扣款金额不一致（应为固定金额）")
            if len(merchants) != 1:
                errors.append("场景E：订阅扣款商户不一致")
            if "订阅" not in cats:
                errors.append("场景E：订阅扣款缺少'订阅'类别")
            yms = {t["date"][:7] for t in subs}
            if len(yms) < 2:
                errors.append("场景E：订阅扣款未覆盖多个月份")
            days = {t["date"][8:10] for t in subs}
            if len(days) != 1:
                warnings.append("场景E：订阅扣款日期不是每月同一天（可能因月份天数不足取月末）")

    elif stype == "F":
        family = scenario.get("family") or []
        budget = scenario.get("budget") or {}
        calendar = scenario.get("activity_calendar") or []
        if not family:
            errors.append("场景F：缺少家庭成员")
        if not calendar:
            errors.append("场景F：活动日历为空")
        locked = budget.get("locked_amount")
        planned = round(sum(
            entry.get("budget", 0) for entry in calendar
            if isinstance(entry, dict) and entry.get("status") != "cancelled"
        ), 2)
        if not isinstance(locked, (int, float)) or isinstance(locked, bool) or locked <= 0:
            errors.append("场景F：锁定金额必须是大于 0 的数字")
        elif planned > locked + 0.01:
            errors.append(f"场景F：活动日历预算合计 {planned} 超过锁定金额 {locked}")
        for member in family:
            birthday = (member or {}).get("birthday", "")
            try:
                bday = datetime.strptime(birthday, "%Y-%m-%d")
            except (TypeError, ValueError):
                errors.append("场景F：家庭成员生日格式必须为 YYYY-MM-DD")
                continue
            order_date = _d(bday - timedelta(days=2))
            categories = {entry.get("category") for entry in calendar
                          if isinstance(entry, dict) and entry.get("date") == order_date}
            for needed in ("鲜花", "蛋糕"):
                if needed not in categories:
                    errors.append(f"场景F：生日前 2 天（{order_date}）缺少{needed}订购安排")

    elif stype == "G":
        cards = scenario.get("cards") or []
        card_ids = {card.get("card_id") for card in cards}
        credit_cards = [card for card in cards if card.get("card_type") == "credit"]
        if not cards:
            errors.append("场景G：缺少卡片数据")
        if not credit_cards:
            errors.append("场景G：缺少信用卡")
        bill = scenario.get("credit_card_bill")
        if not isinstance(bill, dict):
            errors.append("场景G：缺少信用卡账单")
        else:
            if bill.get("card_id") not in card_ids:
                errors.append("场景G：账单引用了不存在的卡片")
            total = bill.get("total_amount", 0)
            paid = bill.get("paid_amount", 0)
            outstanding = bill.get("outstanding_amount", 0)
            if abs(round(total - paid, 2) - outstanding) > 0.01:
                errors.append("场景G：账单未还金额与消费、已还金额不一致")
            for card in credit_cards:
                if abs(card.get("credit_limit", 0) - card.get("used_credit", 0)
                       - card.get("available_credit", 0)) > 0.01:
                    errors.append(f"场景G：信用卡 {card.get('card_id')} 额度关系不一致")
        if not scenario.get("card_events"):
            errors.append("场景G：缺少卡片管理事件")

    else:
        errors.append(f"不支持的场景类型：{stype}")

    return (len(errors) == 0, errors + warnings)


# ============================================================================
# 5. 生成与校验的统一入口（优先调用真实模块，缺失时回退到临时实现）
# ============================================================================

def generate_scenario(config: Dict[str, Any]) -> Dict[str, Any]:
    """调用场景生成模块。若 scenario_generator.py 存在则优先使用它。"""
    if HAS_GENERATOR_MODULE:
        return scenario_generator.generate(config)  # type: ignore
    return generate_scenario_fallback(config)


def validate_scenario(scenario: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """双层校验：外部 validator + 内置语义校验，两者都通过才算通过。

    为什么两层都要跑？
    - 外部 validator.py 负责结构、对账和 A~G 专项规则；
    - 内置校验是独立的第二道防线，避免"validator 漏掉某个场景规则"时
      错误数据被静默保存（2026-10-23 之前 C/D/E 就是这样被跳过的）。
    - 两边的问题合并去重后一起返回，方便定位。
    """
    if not HAS_VALIDATOR_MODULE:
        return validate_scenario_fallback(scenario, config)

    external_ok, external_messages = validator.validate(scenario, config)  # type: ignore
    internal_ok, internal_messages = validate_scenario_fallback(scenario, config)

    merged: List[str] = []
    for message in list(external_messages) + list(internal_messages):
        if message not in merged:
            merged.append(message)

    # 注意：内置校验可能返回"提示"（如订阅日期顺延），提示不影响通过
    return (external_ok and internal_ok, merged)


# ============================================================================
# 6. 唯一 ID 生成与文件保存
# ============================================================================

def generate_scenario_id(scenario_type: str) -> str:
    """生成唯一场景 ID，并确保不与已有文件重名（避免覆盖）。"""
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    while True:
        suffix = uuid.uuid4().hex[:6].upper()
        sid = f"SCN_{scenario_type}_{stamp}_{suffix}"
        if not (OUTPUT_DIR / f"{sid}.json").exists():
            return sid


def save_scenario(scenario: Dict[str, Any]) -> Path:
    """把场景保存为 JSON 文件，返回保存路径。

    用 pathlib 处理路径，用 json.dumps 序列化（ensure_ascii=False 保留中文）。
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{scenario['scenario_id']}.json"

    # 双重保险：万一文件已存在（理论上不会），换一个新的 ID 再保存
    if path.exists():
        scenario["scenario_id"] = generate_scenario_id(scenario.get("scenario_type", "X"))
        path = OUTPUT_DIR / f"{scenario['scenario_id']}.json"

    with path.open("w", encoding="utf-8") as f:
        json.dump(scenario, f, ensure_ascii=False, indent=2)
    return path


# ============================================================================
# 7. 程序入口与交互循环
# ============================================================================

def print_banner() -> None:
    """打印程序欢迎信息。"""
    print("=" * 60)
    print("  银行场景环境生成 Agent")
    print("  生成虚拟银行业务场景数据（仅供 AI Banking 比赛使用）")
    print("  所有数据均为虚构，不连接真实银行、不执行真实资金操作")
    print("=" * 60)


def print_module_status() -> None:
    """打印三个预留模块的加载状态，方便用户知道当前用的是哪套实现。"""
    print("[模块状态]")
    print(f"  scenario_generator : {'已加载' if HAS_GENERATOR_MODULE else '未找到，使用内置临时实现'}")
    print(f"  validator          : {'已加载' if HAS_VALIDATOR_MODULE else '未找到，使用内置临时实现'}")
    print(f"  models             : {'已加载' if HAS_MODELS_MODULE else '未找到（当前使用 dict 结构）'}")
    print("-" * 60)


def run_one(text: str) -> None:
    """处理单条场景需求：解析 -> 生成 -> 校验 -> 保存 -> 输出结果。"""
    config = parse_requirement(text)
    config["scenario_id"] = generate_scenario_id(config["scenario_type"])
    print(f"[识别] 场景类型：{config['scenario_type']}（{config['scenario_name']}）")

    scenario = generate_scenario(config)

    ok, messages = validate_scenario(scenario, config)
    if not ok:
        # 校验失败：不保存、不标记成功
        print("[校验失败] 场景未通过校验，已放弃保存（不会标记为成功）：")
        for m in messages:
            print(f"  ✗ {m}")
        return

    try:
        path = save_scenario(scenario)
    except (OSError, PermissionError) as exc:
        print(f"[保存失败] 无法写入文件：{exc}")
        return

    print("[校验通过] 场景已生成并保存：")
    print(f"  场景 ID  ：{scenario['scenario_id']}")
    print(f"  场景类型 ：{scenario['scenario_type']}（{scenario['scenario_name']}）")
    print(f"  文件路径 ：{path}")
    for m in messages:
        print(f"  提示：{m}")


def main() -> None:
    """程序主循环：连续创建多个场景，输入 exit 退出。"""
    print_banner()
    print_module_status()
    print("支持场景：A 普通用户 | B 购物支出增加 | C 疑似重复扣款 | D 余额不足 | "
          "E 周期性订阅 | F 家庭生日跨场景联动 | G 信用卡与卡片管理")
    print("示例：创建一个购物支出比上个月增加 800 元的用户")
    print("示例：检测我配偶的生日，锁定 1000 元活动预算并生成活动日历")
    print("示例：生成一张信用卡账单，并模拟卡片挂失和额度调整")

    while True:
        try:
            text = input("\n请输入场景需求（输入 exit 退出）：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not text:
            continue
        if text.lower() in EXIT_KEYWORDS:
            print("已退出，再见！")
            break

        try:
            run_one(text)
        except ScenarioError as exc:
            print(f"[错误] {exc}")
        except Exception as exc:  # 兜底：不让任何一个输入把程序打崩
            print(f"[错误] 处理失败：{exc}")


# 非交互批量生成用的默认需求（--all 时使用），也是七类场景的标准样例描述
DEFAULT_REQUIREMENTS: Dict[str, str] = {
    "A": "生成一个普通银行用户，包含工资收入和日常消费",
    "B": "创建一个购物支出比上个月增加 800 元的用户",
    "C": "生成一个疑似重复扣款的用户",
    "D": "生成一个余额不足导致转账失败的场景",
    "E": "生成一个周期性订阅扣费的场景",
    "F": "检测我配偶的生日，锁定 1000 元活动预算并生成活动日历",
    "G": "生成一个信用卡账单和卡片挂失/额度调整场景",
}


def run_batch(requirements: List[str]) -> int:
    """批量生成场景，返回失败数量。用于 --generate / --all 非交互模式。"""
    failures = 0
    for text in requirements:
        try:
            run_one(text)
        except ScenarioError as exc:
            failures += 1
            print(f"[错误] {exc}")
        except Exception as exc:
            failures += 1
            print(f"[错误] 处理失败：{exc}")
    return failures


def cli(argv: Optional[List[str]] = None) -> int:
    """命令行入口：默认进入交互模式；加参数则批量生成。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="银行场景环境生成 Agent（仅生成虚构数据，不执行真实资金操作）"
    )
    parser.add_argument(
        "--generate", "-g", action="append", metavar="需求",
        help="非交互生成一条场景，可重复使用多次",
    )
    parser.add_argument(
        "--all", action="store_true", help="一次生成 A~G 七类标准样例",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="随机种子，配合 --reference-date 可复现同样的数据",
    )
    parser.add_argument(
        "--reference-date", default=None, metavar="YYYY-MM-DD",
        help="把生成时的'今天'固定为指定日期，便于回归测试",
    )
    args = parser.parse_args(argv)

    set_seed(args.seed)
    if args.reference_date is not None:
        try:
            set_reference_date(args.reference_date)
        except ValueError:
            parser.error("--reference-date 必须是 YYYY-MM-DD 格式")

    if args.all or args.generate:
        print_banner()
        print_module_status()
        if args.seed is not None:
            print(f"[可复现] seed={args.seed}")
        if _REFERENCE_NOW is not None:
            print(f"[可复现] reference_date={args.reference_date}")
        print("-" * 60)

        requirements = args.generate if args.generate else list(DEFAULT_REQUIREMENTS.values())
        return run_batch(requirements)

    main()
    return 0


if __name__ == "__main__":
    # 尽量让 Windows 终端正确显示中文（Python 3.7+ 支持 reconfigure）
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass
    sys.exit(cli())
