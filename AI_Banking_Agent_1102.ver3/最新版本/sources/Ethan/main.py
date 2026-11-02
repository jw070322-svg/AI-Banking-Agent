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
import random
import re
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ============================================================================
# 0. 路径、常量与自定义异常
# ============================================================================

# 项目根目录：main.py 所在目录，所有路径都基于它
BASE_DIR = Path(__file__).resolve().parent

# 生成结果统一输出到 output 目录
OUTPUT_DIR = BASE_DIR / "output"

# 五个第一版必须支持的场景：类型代码 -> 中文名
SCENARIO_TYPE_NAMES: Dict[str, str] = {
    "A": "普通银行用户",
    "B": "购物支出增加",
    "C": "疑似重复扣款",
    "D": "余额不足",
    "E": "周期性订阅",
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
    if scenario_type == "B":
        params["increase_amount"] = round(increase_amount, 2)

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
    """生成带前缀的随机唯一 ID，例如 _rid("T") -> T3F2A9C1D4E5。"""
    return f"{prefix}{uuid.uuid4().hex[:12].upper()}"


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
    now = datetime.now()
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
    now = datetime.now()
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
              transactions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把各部分组成完整的场景 dict（符合统一数据格式）。"""
    return {
        "scenario_id": config["scenario_id"],
        "scenario_name": config["scenario_name"],
        "scenario_type": config["scenario_type"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "user": user,
        "accounts": accounts,
        "transactions": transactions,
        "scenario_requirements": config["requirements"],
    }


def _gen_A(config: Dict[str, Any]) -> Dict[str, Any]:
    """场景 A：普通银行用户。"""
    now = datetime.now()
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
    return _assemble(config, _make_user(user_id),
                     [_make_account(account_id, user_id, initial_balance, balance)], txns)


def _gen_B(config: Dict[str, Any]) -> Dict[str, Any]:
    """场景 B：购物支出增加。第二个月购物总额 = 第一个月购物总额 + increase_amount。"""
    now = datetime.now()
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
    return _assemble(config, _make_user(user_id),
                     [_make_account(account_id, user_id, initial_balance, balance)], txns)


def _gen_C(config: Dict[str, Any]) -> Dict[str, Any]:
    """场景 C：疑似重复扣款。正常交易 + 一组同商户/同金额/同类别/同日期且时间接近的疑似重复交易。"""
    now = datetime.now()
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
    return _assemble(config, _make_user(user_id),
                     [_make_account(account_id, user_id, initial_balance, balance)], txns)


def _gen_D(config: Dict[str, Any]) -> Dict[str, Any]:
    """场景 D：余额不足。转账请求金额 > 可用余额，交易被拒绝，余额不为负。"""
    now = datetime.now()
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
    return _assemble(config, _make_user(user_id),
                     [_make_account(account_id, user_id, initial_balance, balance)], txns)


def _gen_E(config: Dict[str, Any]) -> Dict[str, Any]:
    """场景 E：周期性订阅。多个月份的固定周期扣款，保留商户/金额/日期/订阅类别。"""
    now = datetime.now()
    user_id = _rid("U")
    account_id = _rid("ACC")

    sub_type = random.choice(["视频会员", "音乐会员", "云存储会员", "新闻会员"])
    merchant = random.choice(["某视频平台", "某音乐平台", "某云盘服务", "某资讯平台"])
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
    return _assemble(config, _make_user(user_id),
                     [_make_account(account_id, user_id, initial_balance, balance)], txns)


def generate_scenario_fallback(config: Dict[str, Any]) -> Dict[str, Any]:
    """临时生成器：按场景类型分发到对应的生成函数。"""
    dispatch = {
        "A": _gen_A,
        "B": _gen_B,
        "C": _gen_C,
        "D": _gen_D,
        "E": _gen_E,
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
    """调用校验模块。若 validator.py 存在则优先使用它。"""
    if HAS_VALIDATOR_MODULE:
        return validator.validate(scenario, config)  # type: ignore
    return validate_scenario_fallback(scenario, config)


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
    print("支持场景：A 普通用户 | B 购物支出增加 | C 疑似重复扣款 | D 余额不足 | E 周期性订阅")
    print("示例：创建一个购物支出比上个月增加 800 元的用户")

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


if __name__ == "__main__":
    # 尽量让 Windows 终端正确显示中文（Python 3.7+ 支持 reconfigure）
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass
    main()
