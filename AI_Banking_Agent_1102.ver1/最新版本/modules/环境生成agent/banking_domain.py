"""banking_domain.py —— 银行场景里的"现实世界"要素
=====================================================

main.py 负责"讲故事"（工资、消费、订阅、重复扣款……），本模块负责给这些
故事补上真实用户每天都会碰到的东西：

1. 卡片：借记卡 + 信用卡（额度、已用额度、可用额度、账单日、还款日、状态）；
2. 家庭：配偶、父母、子女、兄弟姐妹，以及他们**下一次**生日；
3. 节日：公历节日 + 母亲节/父亲节（按星期计算）+ 2026–2027 农历节日对照表；
4. 日历与提醒：生日、节日、信用卡还款、订阅续费、工资日、预算锁定、备忘；
5. 小工具：信用卡账单周期计算、卡号脱敏、ID 生成。

对初学者的提醒：
- 这里所有日期都是"下一次发生"的日期，后面会被日历和提醒直接使用；
- 农历节日用 2026–2027 的演示对照表（不是专业历法库），超出范围就自动跳过；
- 所有数据都是虚构的，卡号只保留前 4 位和后 4 位。
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# 常量（validator 也会引用，保证生成和校验用同一套枚举）
# ---------------------------------------------------------------------------

CARD_TYPES = {"debit", "credit"}
CARD_STATUSES = {"active", "frozen", "lost", "closed"}
CARD_EVENT_TYPES = {
    "card_lost",            # 挂失
    "card_frozen",          # 冻结
    "card_unfrozen",        # 解冻
    "limit_adjusted",       # 额度调整
    "transaction_limit_set",  # 交易限额设置
    "card_replaced",        # 补卡
}

EVENT_TYPES = {
    "birthday",             # 家人生日
    "festival",             # 节日
    "bill_due",             # 信用卡还款
    "subscription_renewal",  # 订阅续费
    "salary",               # 工资日
    "budget_lock",          # 活动预算锁定
    "custom",               # 自定义备忘
}
EVENT_CATEGORIES = {
    "birthday": "生日",
    "festival": "节日",
    "bill_due": "信用卡还款",
    "subscription_renewal": "订阅续费",
    "salary": "工资",
    "budget_lock": "预算锁定",
    "custom": "备忘",
}
EVENT_STATUSES = {"planned", "done", "cancelled"}
PRIORITIES = {"high", "medium", "low"}

INSIGHT_TYPES = {
    "duplicate_charge",      # 疑似重复扣款
    "upcoming_bill",         # 信用卡还款临近
    "subscription_renewal",  # 订阅即将续费
    "budget_lock",           # 生日预算已锁定
    "birthday_upcoming",     # 家人生日临近
    "salary_detected",       # 识别到工资
    "unusual_spending",      # 异常消费
    "failed_transfer",       # 转账失败/被拒
}
SEVERITIES = {"high", "medium", "low"}

# 脱敏卡号格式：前 4 位 + 8 个星号 + 后 4 位（中间用空格分隔）
MASKED_CARD_PATTERN = r"\d{4} \*{4} \*{4} \d{4}"

CREDIT_LIMITS = [10000.0, 20000.0, 30000.0, 50000.0]

# ---------------------------------------------------------------------------
# 基础日期工具
# ---------------------------------------------------------------------------


def rid(prefix: str) -> str:
    """可复现的唯一 ID（使用全局 random，配合 set_seed 可固定）。"""
    return f"{prefix}{random.getrandbits(48):012X}"


def to_date_str(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def days_in_month(year: int, month: int) -> int:
    next_month = date(year, month, 28) + timedelta(days=4)
    return (next_month.replace(day=1) - timedelta(days=1)).day


def shift_month(value: date, delta: int) -> date:
    """按月平移，日期越界时取当月最后一天。"""
    index = value.year * 12 + (value.month - 1) + delta
    year, month_index = divmod(index, 12)
    month = month_index + 1
    return date(year, month, min(value.day, days_in_month(year, month)))


def latest_day_of_month(reference: date, day: int) -> date:
    """返回不晚于 reference 的、最近一个"某月 day 号"。"""
    day = min(max(1, day), 28)
    candidate = date(reference.year, reference.month, day)
    if candidate > reference:
        previous = shift_month(date(reference.year, reference.month, 1), -1)
        candidate = date(previous.year, previous.month, min(day, days_in_month(previous.year, previous.month)))
    return candidate


def next_day_of_month(reference: date, day: int) -> date:
    """返回不早于 reference 的、下一个"某月 day 号"。"""
    day = min(max(1, day), 28)
    candidate = date(reference.year, reference.month, day)
    if candidate < reference:
        following = shift_month(date(reference.year, reference.month, 1), 1)
        candidate = date(following.year, following.month, min(day, days_in_month(following.year, following.month)))
    return candidate


# ---------------------------------------------------------------------------
# 节日（公历 + 星期规则 + 2026–2027 农历对照表）
# ---------------------------------------------------------------------------

FIXED_FESTIVALS: Dict[Tuple[int, int], str] = {
    (1, 1): "元旦",
    (2, 14): "情人节",
    (3, 8): "妇女节",
    (5, 1): "劳动节",
    (6, 1): "儿童节",
    (9, 10): "教师节",
    (10, 1): "国庆节",
    (12, 25): "圣诞节",
}

# 演示用农历节日对照表（来源：公开日历标注；超出 2026–2027 自动不生成）
LUNAR_FESTIVALS: Dict[int, List[Tuple[str, int, int]]] = {
    2026: [("春节", 2, 17), ("元宵节", 3, 3), ("端午节", 6, 19),
           ("七夕", 8, 19), ("中秋节", 9, 25), ("重阳节", 10, 18)],
    2027: [("春节", 2, 6), ("元宵节", 2, 20), ("端午节", 6, 9),
           ("七夕", 8, 8), ("中秋节", 9, 15), ("重阳节", 10, 8)],
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """某月第 n 个星期 weekday（Monday=0）。用于母亲节、父亲节。"""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def festival_dates(year: int) -> List[Tuple[date, str]]:
    """返回某一年包含的所有节日日期。"""
    events: List[Tuple[date, str]] = [
        (date(year, month, day), name) for (month, day), name in FIXED_FESTIVALS.items()
    ]
    events.append((_nth_weekday(year, 5, 6, 2), "母亲节"))   # 5 月第 2 个星期日
    events.append((_nth_weekday(year, 6, 6, 3), "父亲节"))   # 6 月第 3 个星期日
    events.append((_nth_weekday(year, 11, 3, 4), "感恩节"))  # 11 月第 4 个星期四
    for name, month, day in LUNAR_FESTIVALS.get(year, []):
        events.append((date(year, month, day), name))
    return sorted(events)


def upcoming_festivals(now: datetime, horizon_days: int = 90) -> List[Tuple[date, str]]:
    """返回从现在起 horizon_days 天内（含今天）的节日。"""
    today = now.date()
    limit = today + timedelta(days=horizon_days)
    results: List[Tuple[date, str]] = []
    seen = set()
    for year in (today.year, today.year + 1):
        for event_date, name in festival_dates(year):
            if today <= event_date <= limit and (event_date, name) not in seen:
                seen.add((event_date, name))
                results.append((event_date, name))
    return sorted(results)


# ---------------------------------------------------------------------------
# 家庭成员
# ---------------------------------------------------------------------------

# (关系, 年龄范围)
FAMILY_RELATIONS: List[Tuple[str, Tuple[int, int]]] = [
    ("配偶", (26, 40)),
    ("母亲", (48, 62)),
    ("父亲", (50, 65)),
    ("子女", (6, 16)),
    ("兄弟姐妹", (22, 40)),
]


def make_family(
    now: datetime,
    count: Optional[int] = None,
    window_days: Optional[int] = None,
    relations: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """生成 1~3 位家庭成员，birthday 是**下一次**生日。

    window_days：只在该天数窗口内挑生日（场景 F 用，保证在预算锁定月内）。
    relations：限定关系，例如 ["配偶"]。
    """
    if count is None:
        count = random.randint(1, 3)
    pool = [
        item for item in FAMILY_RELATIONS
        if relations is None or item[0] in relations
    ] or FAMILY_RELATIONS
    relations_chosen = random.sample(pool, k=min(count, len(pool)))

    members: List[Dict[str, Any]] = []
    used_dates = set()
    for relation, (min_age, max_age) in relations_chosen:
        age_turning = random.randint(min_age, max_age)
        if window_days is not None:
            offset = random.randint(3, max(3, window_days))
            birthday = (now + timedelta(days=offset)).date()
        else:
            month = random.randint(1, 12)
            day = random.randint(1, min(28, days_in_month(now.year, month)))
            birthday = date(now.year, month, day)
            if birthday <= now.date():
                birthday = date(now.year + 1, month, day)
        if birthday in used_dates:
            continue
        used_dates.add(birthday)
        members.append({
            "member_id": rid("FAM"),
            "relation": relation,
            "birthday": to_date_str(birthday),
            "birth_year": birthday.year - age_turning,
            "age_turning": age_turning,
        })
    return members


# ---------------------------------------------------------------------------
# 卡片
# ---------------------------------------------------------------------------


def masked_card_number(prefix: str = "6222") -> str:
    return f"{prefix} **** **** {random.randint(1000, 9999)}"


def make_cards(
    user_id: str,
    account_id: str,
    now: datetime,
    used_credit: float = 0.0,
    credit_limit: Optional[float] = None,
    credit_status: str = "active",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """生成一张借记卡和一张信用卡。

    信用卡额度关系：available_credit = credit_limit - used_credit。
    used_credit 在生成账单后会根据"未还金额"重新写入。
    """
    if credit_limit is None:
        credit_limit = random.choice(CREDIT_LIMITS)
    statement_day = random.randint(3, 10)
    due_day = statement_day + 18  # 21~28，保证不超过 28 号

    opened_debit = (now - timedelta(days=random.randint(300, 2500))).date()
    opened_credit = (now - timedelta(days=random.randint(180, 1800))).date()

    debit = {
        "card_id": rid("CARD"),
        "user_id": user_id,
        "account_id": account_id,
        "card_type": "debit",
        "card_number_masked": masked_card_number(),
        "brand": "银联",
        "status": "active",
        "currency": "CNY",
        "opened_date": to_date_str(opened_debit),
        "transaction_limit": {"daily": 50000.0, "single": 20000.0},
    }

    credit = {
        "card_id": rid("CARD"),
        "user_id": user_id,
        "account_id": account_id,
        "card_type": "credit",
        "card_number_masked": masked_card_number("6225"),
        "brand": random.choice(["银联", "Visa", "Mastercard"]),
        "status": credit_status,
        "currency": "CNY",
        "opened_date": to_date_str(opened_credit),
        "credit_limit": round(float(credit_limit), 2),
        "used_credit": round(float(used_credit), 2),
        "available_credit": round(float(credit_limit) - float(used_credit), 2),
        "statement_day": statement_day,
        "due_day": due_day,
        "transaction_limit": {"daily": 20000.0, "single": 10000.0},
    }
    return debit, credit


def statement_period(card: Dict[str, Any], now: datetime) -> Tuple[date, date, date]:
    """返回最近一个账单周期：(周期开始, 账单日, 还款日)。"""
    statement_day = int(card.get("statement_day", 5))
    statement_date = latest_day_of_month(now.date(), statement_day)
    previous_statement = shift_month(statement_date, -1)
    cycle_start = previous_statement + timedelta(days=1)
    due_date = statement_date + timedelta(days=18)
    return cycle_start, statement_date, due_date


def next_card_due_date(card: Dict[str, Any], now: datetime) -> date:
    """返回下一次信用卡还款日（如果本周期还款日已过，就取下一周期）。"""
    _, statement_date, due_date = statement_period(card, now)
    if due_date < now.date():
        next_statement = shift_month(statement_date, 1)
        due_date = next_statement + timedelta(days=18)
    return due_date


def make_credit_card_bill(
    card: Dict[str, Any],
    items: Sequence[Dict[str, Any]],
    paid_amount: float,
    now: datetime,
) -> Dict[str, Any]:
    """根据本期消费生成信用卡账单。

    账单关系：
    - total_amount        = 本期消费合计
    - outstanding_amount  = total_amount - paid_amount
    - status              = paid / partial / unpaid
    - 账单未还金额会写回卡片的 used_credit（available = limit - used）
    """
    cycle_start, statement_date, due_date = statement_period(card, now)
    total = round(sum(float(item["amount"]) for item in items), 2)
    paid = round(min(max(float(paid_amount), 0.0), total), 2)
    outstanding = round(total - paid, 2)
    if outstanding <= 0.005:
        status = "paid"
        outstanding = 0.0
    elif paid > 0:
        status = "partial"
    else:
        status = "unpaid"

    bill = {
        "bill_id": rid("BILL"),
        "card_id": card["card_id"],
        "cycle_start": to_date_str(cycle_start),
        "statement_date": to_date_str(statement_date),
        "due_date": to_date_str(due_date),
        "items": list(items),
        "total_amount": total,
        "minimum_payment": round(min(total * 0.1, outstanding) if outstanding else 0.0, 2),
        "paid_amount": paid,
        "outstanding_amount": outstanding,
        "status": status,
        "currency": "CNY",
    }
    apply_bill_to_card(card, bill)
    return bill


def apply_bill_to_card(card: Dict[str, Any], bill: Dict[str, Any]) -> None:
    """把账单未还金额写回信用卡的已用/可用额度。"""
    limit = float(card.get("credit_limit", 0.0))
    used = round(float(bill.get("outstanding_amount", 0.0)), 2)
    card["used_credit"] = used
    card["available_credit"] = round(limit - used, 2)


# ---------------------------------------------------------------------------
# 日历与提醒
# ---------------------------------------------------------------------------

CUSTOM_MEMOS: List[Tuple[str, str, str]] = [
    ("预约年度体检", "备忘", "体检需空腹，提前 8 小时禁食"),
    ("车险续保", "备忘", "对比两家报价后续保"),
    ("信用卡年费减免确认", "备忘", "刷满 6 笔可免年费"),
    ("公积金提取材料", "备忘", "准备身份证和租房合同"),
    ("家庭照片冲印", "备忘", "选择 20 张照片冲洗"),
]


def _event(
    *,
    event_date: date,
    event_type: str,
    title: str,
    remind_days_before: int,
    priority: str,
    now_date: date,
    related_member_id: Optional[str] = None,
    related_card_id: Optional[str] = None,
    related_subscription_id: Optional[str] = None,
    budget: Optional[float] = None,
    notes: str = "",
) -> Dict[str, Any]:
    """构造一条日历事件，并自动算出提醒日期。"""
    remind_date = event_date - timedelta(days=remind_days_before)
    return {
        "event_id": rid("EVT"),
        "date": to_date_str(event_date),
        "event_type": event_type,
        "category": EVENT_CATEGORIES[event_type],
        "title": title,
        "related_member_id": related_member_id,
        "related_card_id": related_card_id,
        "related_subscription_id": related_subscription_id,
        "remind_days_before": int(remind_days_before),
        "remind_date": to_date_str(remind_date),
        "priority": priority,
        "budget": round(float(budget), 2) if budget is not None else None,
        "status": "done" if event_date < now_date else "planned",
        "notes": notes,
    }


def make_calendar_events(
    now: datetime,
    family: Sequence[Dict[str, Any]],
    credit_cards: Sequence[Dict[str, Any]],
    *,
    subscriptions: Optional[Sequence[Dict[str, Any]]] = None,
    salary_day: Optional[int] = None,
    budget: Optional[Dict[str, Any]] = None,
    festival_horizon_days: int = 90,
) -> List[Dict[str, Any]]:
    """生成统一日历：家人生日、节日、还款日、订阅续费、工资日、预算锁定、备忘。"""
    today = now.date()
    events: List[Dict[str, Any]] = []

    # 1) 家人生日：提前 7 天提醒
    for member in family:
        try:
            birthday = datetime.strptime(member["birthday"], "%Y-%m-%d").date()
        except (KeyError, TypeError, ValueError):
            continue
        relation = member.get("relation", "家人")
        events.append(_event(
            event_date=birthday,
            event_type="birthday",
            title=f"{relation}生日",
            remind_days_before=7,
            priority="high",
            now_date=today,
            related_member_id=member.get("member_id"),
            notes="提前准备礼物或鲜花",
        ))

    # 2) 节日：提前 3 天提醒
    for festival_date, name in upcoming_festivals(now, festival_horizon_days):
        events.append(_event(
            event_date=festival_date,
            event_type="festival",
            title=name,
            remind_days_before=3,
            priority="medium",
            now_date=today,
            notes=f"{name}问候与安排",
        ))

    # 3) 信用卡还款：有未还金额才提醒
    for card in credit_cards:
        if float(card.get("used_credit", 0.0)) <= 0:
            continue
        due_date = next_card_due_date(card, now)
        events.append(_event(
            event_date=due_date,
            event_type="bill_due",
            title=f"信用卡还款 {card.get('card_number_masked', '')}".strip(),
            remind_days_before=3,
            priority="high",
            now_date=today,
            related_card_id=card.get("card_id"),
            budget=float(card.get("used_credit", 0.0)),
            notes="确保绑定账户余额充足",
        ))

    # 4) 订阅续费：提前 2 天提醒
    for subscription in subscriptions or []:
        try:
            next_charge = datetime.strptime(subscription["next_charge_date"], "%Y-%m-%d").date()
        except (KeyError, TypeError, ValueError):
            continue
        if subscription.get("status") != "active":
            continue
        events.append(_event(
            event_date=next_charge,
            event_type="subscription_renewal",
            title=f"{subscription.get('merchant', '订阅服务')}续费",
            remind_days_before=2,
            priority="medium",
            now_date=today,
            related_subscription_id=subscription.get("subscription_id"),
            budget=float(subscription.get("amount", 0.0)),
            notes="如不需要可提前取消",
        ))

    # 5) 工资日：提前 1 天提醒
    if salary_day:
        payday = next_day_of_month(today + timedelta(days=1), salary_day)
        events.append(_event(
            event_date=payday,
            event_type="salary",
            title="工资到账日",
            remind_days_before=1,
            priority="low",
            now_date=today,
            notes="可安排本月储蓄与预算",
        ))

    # 6) 生日月预算锁定（场景 F）
    if budget and budget.get("lock_month"):
        try:
            lock_start = datetime.strptime(f"{budget['lock_month']}-01", "%Y-%m-%d").date()
        except (TypeError, ValueError):
            lock_start = None
        if lock_start is not None:
            # 当月已经进入锁定状态时，把事件放在今天，日历上才看得到
            lock_end = shift_month(lock_start, 1) - timedelta(days=1)
            event_date = today if lock_start <= today <= lock_end else lock_start
            events.append(_event(
                event_date=event_date,
                event_type="budget_lock",
                title="生日活动预算锁定",
                remind_days_before=0,
                priority="medium",
                now_date=today,
                budget=float(budget.get("locked_amount", 0.0)),
                notes="锁定金额用于鲜花、蛋糕等活动支出",
            ))

    # 7) 自定义备忘：未来 30 天内随机挑 1~2 条
    memo_count = random.randint(1, 2)
    for title, category, note in random.sample(CUSTOM_MEMOS, k=memo_count):
        memo_date = today + timedelta(days=random.randint(2, 30))
        events.append(_event(
            event_date=memo_date,
            event_type="custom",
            title=title,
            remind_days_before=random.choice([1, 2, 3]),
            priority=random.choice(["low", "medium"]),
            now_date=today,
            notes=note,
        ))

    events.sort(key=lambda item: (item["date"], item["event_id"]))
    return events
