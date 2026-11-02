"""validator.py —— 银行场景数据的独立校验模块
=====================================================

职责：
1. 检查场景的基本结构（用户 / 账户 / 交易 / 金额 / 引用 / 日期 / 状态）；
2. 按"已完成流水"对账：期末余额 = 期初余额 + 收入、转入、退款 - 支出、转出；
3. 对 A~F 六类场景做**专项语义校验**，而且所有结论都从真实流水重新计算，
   不轻信配置或文本里写的数字。

对初学者的一句话说明：
- 结构校验回答"数据格式对不对"；
- 语义校验回答"这个场景是不是真的满足我们要演示的业务目标"。
  两者缺一不可：格式对但语义不成立的场景，会让主 Agent 演示失败。

所有数据均为虚构，不连接真实银行、不执行真实资金操作。
"""

import math
import re
from datetime import date as date_cls
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from banking_domain import (
    CARD_EVENT_TYPES,
    CARD_STATUSES,
    CARD_TYPES,
    EVENT_CATEGORIES,
    EVENT_STATUSES,
    EVENT_TYPES,
    INSIGHT_TYPES,
    MASKED_CARD_PATTERN,
    PRIORITIES,
    SEVERITIES,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 合法的交易类型（金额统一非负，方向由类型表达）
VALID_TRANSACTION_TYPES = {
    "income",        # 收入（如工资）：余额增加
    "expense",       # 支出（如购物、餐饮）：余额减少
    "transfer_in",   # 转入：余额增加，内部转账不算消费
    "transfer_out",  # 转出：余额减少，内部转账不算消费
    "refund",        # 退款：余额增加
}

# 合法的交易状态。completed 表示已入账；rejected/pending/failed/reversed 不改变余额。
VALID_TRANSACTION_STATUSES = {"completed", "pending", "rejected", "failed", "reversed"}

# 使余额增加 / 减少的交易类型
INCREASING_TYPES = {"income", "transfer_in", "refund"}
DECREASING_TYPES = {"expense", "transfer_out"}

REQUIRED_FIELDS = ["scenario_id", "scenario_type", "user", "accounts", "transactions"]

DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
MONTH_PATTERN = re.compile(r"\d{4}-\d{2}")


# ---------------------------------------------------------------------------
# 小工具函数
# ---------------------------------------------------------------------------

def _is_finite_number(value: Any) -> bool:
    """判断是不是有限数字（排除 bool、字符串、NaN、无穷大）。"""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _parse_date(value: Any) -> Optional[date_cls]:
    """把 'YYYY-MM-DD' 解析成 date；格式或日期不合法时返回 None。"""
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        return None
    try:
        year, month, day = (int(part) for part in value.split("-"))
        return date_cls(year, month, day)
    except ValueError:
        return None


def _parse_month(value: Any) -> Optional[Tuple[int, int]]:
    """把 'YYYY-MM' 解析成 (年, 月)；不合法时返回 None。"""
    if not isinstance(value, str) or not MONTH_PATTERN.fullmatch(value):
        return None
    year, month = (int(part) for part in value.split("-"))
    if not 1 <= month <= 12:
        return None
    return year, month


def _month_index(year: int, month: int) -> int:
    """把 (年, 月) 转成一个连续的整数序号，便于判断"A 的下一个月是不是 B"。"""
    return year * 12 + month


def _txn_labels(transactions: List[Any]) -> List[str]:
    """给每笔交易一个可读标签，用于错误信息（缺 transaction_id 时用序号）。"""
    labels: List[str] = []
    for index, transaction in enumerate(transactions):
        if isinstance(transaction, dict) and transaction.get("transaction_id"):
            labels.append(str(transaction["transaction_id"]))
        else:
            labels.append(f"第{index + 1}笔")
    return labels


# ---------------------------------------------------------------------------
# 1. 结构校验
# ---------------------------------------------------------------------------

def _validate_user(user: Any, errors: List[str]) -> None:
    """检查用户信息。"""
    if not isinstance(user, dict):
        errors.append("user 必须是字典")
        return
    if not user:
        errors.append("用户信息不能为空")
        return
    user_id = user.get("user_id")
    if user_id is not None and (not isinstance(user_id, str) or not user_id.strip()):
        errors.append("用户 user_id 必须是非空字符串")


def _validate_accounts(accounts: Any, errors: List[str]) -> List[Dict[str, Any]]:
    """检查账户列表，返回账户字典列表。"""
    if not isinstance(accounts, list) or not accounts:
        errors.append("accounts 必须是非空列表")
        return []

    account_ids = set()
    valid_accounts: List[Dict[str, Any]] = []

    for account in accounts:
        if not isinstance(account, dict):
            errors.append("账户信息格式错误")
            continue
        valid_accounts.append(account)

        account_id = account.get("account_id")
        if not account_id:
            errors.append("账户缺少 account_id")
        elif account_id in account_ids:
            errors.append(f"账户 ID 重复：{account_id}")
        else:
            account_ids.add(account_id)

        for field in ("initial_balance", "balance"):
            if field in account:
                value = account[field]
                if not _is_finite_number(value):
                    errors.append(f"账户 {account_id} 的 {field} 不是有效数字")
                elif value < 0:
                    errors.append(f"账户 {account_id} 的 {field} 不能为负数")

    return valid_accounts


def _validate_transactions(
    transactions: Any,
    account_ids: set,
    errors: List[str],
) -> Tuple[List[Dict[str, Any]], set, bool, bool]:
    """检查交易字段，返回 (交易列表, 交易ID集合, 是否有收入, 是否有支出)。"""
    if not isinstance(transactions, list) or not transactions:
        errors.append("transactions 必须是非空列表")
        return [], set(), False, False

    transaction_ids = set()
    has_income = False
    has_expense = False
    valid_transactions: List[Dict[str, Any]] = []

    for transaction in transactions:
        if not isinstance(transaction, dict):
            errors.append("交易记录格式错误")
            continue
        valid_transactions.append(transaction)

        transaction_id = transaction.get("transaction_id")

        if not transaction_id:
            errors.append("交易缺少 transaction_id")
        elif transaction_id in transaction_ids:
            errors.append(f"交易 ID 重复：{transaction_id}")
        else:
            transaction_ids.add(transaction_id)

        # 金额：非负有限数字（bool 不算数字）
        amount = transaction.get("amount")
        if not _is_finite_number(amount):
            errors.append(f"交易 {transaction_id} 的金额不是有效数字")
        elif amount < 0:
            errors.append(f"交易 {transaction_id} 的金额不能为负数")

        # 账户引用
        account_id = transaction.get("account_id")
        if account_id not in account_ids:
            errors.append(f"交易 {transaction_id} 引用了不存在的账户：{account_id}")

        # 交易类型
        transaction_type = transaction.get("transaction_type")
        if transaction_type in INCREASING_TYPES:
            has_income = True
        elif transaction_type in DECREASING_TYPES:
            has_expense = True
        else:
            errors.append(f"交易 {transaction_id} 的 transaction_type 不正确")

        # 交易状态（缺省视为 completed，兼容旧数据）
        status = transaction.get("status", "completed")
        if status not in VALID_TRANSACTION_STATUSES:
            errors.append(f"交易 {transaction_id} 的 status 不正确：{status}")

        # 日期：字段存在时必须是合法的 YYYY-MM-DD（旧测试数据可以不带日期）
        if "date" in transaction and _parse_date(transaction.get("date")) is None:
            errors.append(f"交易 {transaction_id} 的日期格式必须为 YYYY-MM-DD：{transaction.get('date')}")

        # 商户 / 类别：字段存在时必须是字符串
        for field in ("merchant", "category"):
            if field in transaction and not isinstance(transaction[field], str):
                errors.append(f"交易 {transaction_id} 的 {field} 必须是字符串")

    return valid_transactions, transaction_ids, has_income, has_expense


def _check_balance_reconciliation(
    accounts: List[Dict[str, Any]],
    transactions: List[Dict[str, Any]],
    errors: List[str],
) -> None:
    """对账：期末余额 = 期初余额 + 已完成流水净额。

    rejected / pending 等未完成交易不影响账户余额。
    """
    balance_changes: Dict[str, float] = {
        account.get("account_id"): 0.0
        for account in accounts
        if account.get("account_id") is not None
    }

    for transaction in transactions:
        if transaction.get("status", "completed") != "completed":
            continue
        account_id = transaction.get("account_id")
        amount = transaction.get("amount")
        if account_id not in balance_changes or not _is_finite_number(amount):
            continue
        if transaction.get("transaction_type") in INCREASING_TYPES:
            balance_changes[account_id] += amount
        elif transaction.get("transaction_type") in DECREASING_TYPES:
            balance_changes[account_id] -= amount

    for account in accounts:
        account_id = account.get("account_id")
        initial = account.get("initial_balance")
        ending = account.get("balance")
        if (
            account_id in balance_changes
            and _is_finite_number(initial)
            and _is_finite_number(ending)
        ):
            calculated = round(initial + balance_changes[account_id], 2)
            if abs(calculated - ending) > 0.01:
                errors.append(
                    f"账户 {account_id} 余额不一致：记录 {ending}，按已完成流水计算为 {calculated}"
                )


# ---------------------------------------------------------------------------
# 2. 卡片、家庭、日历、订阅、智能洞察（所有场景通用）
# ---------------------------------------------------------------------------

def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_cards(
    cards: Any,
    account_ids: set,
    errors: List[str],
) -> Dict[str, Dict[str, Any]]:
    """检查卡片列表，返回 card_id -> 卡片 的映射。"""
    if cards is None:
        return {}
    if not isinstance(cards, list):
        errors.append("cards 必须是列表")
        return {}

    cards_by_id: Dict[str, Dict[str, Any]] = {}
    for card in cards:
        if not isinstance(card, dict):
            errors.append("卡片信息格式错误")
            continue
        card_id = card.get("card_id")
        if not card_id:
            errors.append("卡片缺少 card_id")
            continue
        if card_id in cards_by_id:
            errors.append(f"卡片 ID 重复：{card_id}")
        cards_by_id[card_id] = card

        card_type = card.get("card_type")
        if card_type not in CARD_TYPES:
            errors.append(f"卡片 {card_id} 的 card_type 不正确：{card_type}")
        if card.get("status") not in CARD_STATUSES:
            errors.append(f"卡片 {card_id} 的 status 不正确：{card.get('status')}")
        if not isinstance(card.get("card_number_masked"), str) or not re.fullmatch(
            MASKED_CARD_PATTERN, card.get("card_number_masked", "")
        ):
            errors.append(f"卡片 {card_id} 的卡号必须是脱敏格式：6222 **** **** 1234")
        if card.get("account_id") not in account_ids:
            errors.append(f"卡片 {card_id} 引用了不存在的账户：{card.get('account_id')}")

        transaction_limit = card.get("transaction_limit")
        if transaction_limit is not None:
            if not isinstance(transaction_limit, dict):
                errors.append(f"卡片 {card_id} 的 transaction_limit 必须是字典")
            else:
                for field in ("daily", "single"):
                    value = transaction_limit.get(field)
                    if not _is_finite_number(value) or value < 0:
                        errors.append(f"卡片 {card_id} 的 {field} 限额必须是非负数字")

        if card_type == "credit":
            limit = card.get("credit_limit")
            used = card.get("used_credit")
            available = card.get("available_credit")
            for field, value in (("credit_limit", limit), ("used_credit", used), ("available_credit", available)):
                if not _is_finite_number(value) or value < 0:
                    errors.append(f"信用卡 {card_id} 的 {field} 必须是非负数字")
            if _is_finite_number(limit) and _is_finite_number(used) and _is_finite_number(available):
                if abs(round(limit - used, 2) - available) > 0.01:
                    errors.append(
                        f"信用卡 {card_id} 额度关系不一致：{limit} - {used} != {available}"
                    )
            statement_day = card.get("statement_day")
            due_day = card.get("due_day")
            if not _is_non_negative_int(statement_day) or not 1 <= statement_day <= 28:
                errors.append(f"信用卡 {card_id} 的 statement_day 必须是 1~28 的整数")
            if not _is_non_negative_int(due_day) or not 1 <= due_day <= 28:
                errors.append(f"信用卡 {card_id} 的 due_day 必须是 1~28 的整数")
            if _is_non_negative_int(statement_day) and _is_non_negative_int(due_day) and due_day <= statement_day:
                errors.append(f"信用卡 {card_id} 的还款日必须晚于账单日")

    return cards_by_id


def _validate_credit_card_bill(
    bill: Any,
    cards_by_id: Dict[str, Dict[str, Any]],
    errors: List[str],
) -> None:
    """检查信用卡账单：明细合计、还款、未还金额与卡片已用额度一致。"""
    if bill is None:
        return
    if not isinstance(bill, dict):
        errors.append("credit_card_bill 必须是字典")
        return

    card = cards_by_id.get(bill.get("card_id"))
    if card is None:
        errors.append(f"账单引用了不存在的卡片：{bill.get('card_id')}")
        return
    if card.get("card_type") != "credit":
        errors.append("credit_card_bill 必须关联信用卡")

    cycle_start = _parse_date(bill.get("cycle_start"))
    statement_date = _parse_date(bill.get("statement_date"))
    due_date = _parse_date(bill.get("due_date"))
    if cycle_start is None or statement_date is None or due_date is None:
        errors.append("账单周期日期必须是合法的 YYYY-MM-DD")
    else:
        if not cycle_start < statement_date < due_date:
            errors.append("账单周期应满足：周期开始 < 账单日 < 还款日")

    items = bill.get("items")
    if not isinstance(items, list) or not items:
        errors.append("账单 items 必须是非空列表")
        items = []

    items_total = 0.0
    item_ids = set()
    for item in items:
        if not isinstance(item, dict):
            errors.append("账单明细格式错误")
            continue
        item_id = item.get("transaction_id")
        if item_id in item_ids:
            errors.append(f"账单明细 ID 重复：{item_id}")
        item_ids.add(item_id)
        if item.get("card_id") != bill.get("card_id"):
            errors.append(f"账单明细 {item_id} 的 card_id 与账单不一致")
        if _parse_date(item.get("date")) is None:
            errors.append(f"账单明细 {item_id} 的日期格式必须为 YYYY-MM-DD")
        if item.get("status", "completed") != "completed":
            errors.append(f"账单明细 {item_id} 必须是已完成交易")
        amount = item.get("amount")
        if not _is_finite_number(amount) or amount < 0:
            errors.append(f"账单明细 {item_id} 的金额必须是非负数字")
            continue
        item_type = item.get("transaction_type")
        if item_type == "expense":
            items_total += amount
        elif item_type == "refund":
            items_total -= amount
        else:
            errors.append(f"账单明细 {item_id} 的类型必须是 expense 或 refund")
    items_total = round(items_total, 2)

    total = bill.get("total_amount")
    paid = bill.get("paid_amount")
    outstanding = bill.get("outstanding_amount")
    minimum = bill.get("minimum_payment")
    for field, value in (
        ("total_amount", total), ("paid_amount", paid),
        ("outstanding_amount", outstanding), ("minimum_payment", minimum),
    ):
        if not _is_finite_number(value) or value < 0:
            errors.append(f"账单 {field} 必须是非负数字")

    if _is_finite_number(total) and items:
        if abs(items_total - round(total, 2)) > 0.01:
            errors.append(f"账单合计 {total} 与明细合计 {items_total} 不一致")
    if _is_finite_number(total) and _is_finite_number(paid) and _is_finite_number(outstanding):
        if abs(round(total - paid, 2) - outstanding) > 0.01:
            errors.append(f"账单未还金额 {outstanding} != 合计 {total} - 已还 {paid}")
    if _is_finite_number(minimum) and _is_finite_number(outstanding):
        if minimum > outstanding + 0.01:
            errors.append("账单最低还款额不能超过未还金额")

    status = bill.get("status")
    if status not in {"paid", "partial", "unpaid"}:
        errors.append(f"账单状态不正确：{status}")
    elif _is_finite_number(paid) and _is_finite_number(outstanding):
        if status == "paid" and outstanding > 0.01:
            errors.append("账单标记为已还清，但仍有未还金额")
        if status == "partial" and (paid <= 0 or outstanding <= 0.01):
            errors.append("账单标记为部分还款，但已还金额或不满足条件")
        if status == "unpaid" and paid > 0.01:
            errors.append("账单标记为未还款，但已有还款金额")

    used = card.get("used_credit")
    if _is_finite_number(used) and _is_finite_number(outstanding):
        if abs(round(outstanding, 2) - used) > 0.01:
            errors.append(
                f"信用卡已用额度 {used} 与账单未还金额 {outstanding} 不一致"
            )


def _validate_family(family: Any, errors: List[str]) -> Dict[str, Dict[str, Any]]:
    """检查家庭成员，返回 member_id -> 成员 的映射。"""
    if family is None:
        return {}
    if not isinstance(family, list) or not family:
        errors.append("family 必须是非空列表")
        return {}

    members: Dict[str, Dict[str, Any]] = {}
    for member in family:
        if not isinstance(member, dict):
            errors.append("家庭成员信息格式错误")
            continue
        member_id = member.get("member_id")
        if not member_id:
            errors.append("家庭成员缺少 member_id")
            continue
        if member_id in members:
            errors.append(f"家庭成员 ID 重复：{member_id}")
        members[member_id] = member
        if not isinstance(member.get("relation"), str) or not member.get("relation"):
            errors.append(f"家庭成员 {member_id} 缺少 relation")
        birthday = _parse_date(member.get("birthday"))
        birth_year = member.get("birth_year")
        age_turning = member.get("age_turning")
        if birthday is None:
            errors.append(f"家庭成员 {member_id} 的生日必须是 YYYY-MM-DD")
        if not _is_non_negative_int(birth_year):
            errors.append(f"家庭成员 {member_id} 的 birth_year 必须是整数")
        if not _is_non_negative_int(age_turning):
            errors.append(f"家庭成员 {member_id} 的 age_turning 必须是整数")
        if birthday is not None and _is_non_negative_int(birth_year) and _is_non_negative_int(age_turning):
            if birthday.year - birth_year != age_turning:
                errors.append(f"家庭成员 {member_id} 的年龄与出生年份不一致")
    return members


def _validate_subscriptions(
    subscriptions: Any,
    transactions: List[Dict[str, Any]],
    errors: List[str],
) -> Dict[str, Dict[str, Any]]:
    """检查订阅区块，返回 subscription_id -> 订阅 的映射。"""
    if subscriptions is None:
        return {}
    if not isinstance(subscriptions, list):
        errors.append("subscriptions 必须是列表")
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for subscription in subscriptions:
        if not isinstance(subscription, dict):
            errors.append("订阅信息格式错误")
            continue
        subscription_id = subscription.get("subscription_id")
        if not subscription_id:
            errors.append("订阅缺少 subscription_id")
            continue
        if subscription_id in result:
            errors.append(f"订阅 ID 重复：{subscription_id}")
        result[subscription_id] = subscription

        merchant = subscription.get("merchant")
        if not isinstance(merchant, str) or not merchant:
            errors.append(f"订阅 {subscription_id} 缺少 merchant")
        amount = subscription.get("amount")
        if not _is_finite_number(amount) or amount <= 0:
            errors.append(f"订阅 {subscription_id} 的金额必须大于 0")
        next_charge = _parse_date(subscription.get("next_charge_date"))
        if next_charge is None:
            errors.append(f"订阅 {subscription_id} 的 next_charge_date 必须是 YYYY-MM-DD")
        if subscription.get("status") not in {"active", "cancelled"}:
            errors.append(f"订阅 {subscription_id} 的 status 不正确")
        if subscription.get("cycle") not in {"monthly", "quarterly", "yearly"}:
            errors.append(f"订阅 {subscription_id} 的 cycle 不正确")

        # 订阅金额要能从真实扣款流水里找到依据
        charges = [
            t for t in transactions
            if t.get("merchant") == merchant and t.get("category") == "订阅"
        ]
        if charges and _is_finite_number(amount):
            if any(abs(float(t.get("amount", 0)) - amount) > 0.01 for t in charges):
                errors.append(f"订阅 {subscription_id} 的金额与历史扣款不一致")

    return result


def _validate_calendar_events(
    events: Any,
    family_ids: set,
    card_ids: set,
    subscription_ids: set,
    errors: List[str],
) -> Dict[str, Dict[str, Any]]:
    """检查日历事件：时间、提醒日期、关联对象。"""
    if events is None:
        return {}
    if not isinstance(events, list) or not events:
        errors.append("calendar_events 必须是非空列表")
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict):
            errors.append("日历事件格式错误")
            continue
        event_id = event.get("event_id")
        if not event_id:
            errors.append("日历事件缺少 event_id")
            continue
        if event_id in result:
            errors.append(f"日历事件 ID 重复：{event_id}")
        result[event_id] = event

        event_type = event.get("event_type")
        if event_type not in EVENT_TYPES:
            errors.append(f"日历事件 {event_id} 的 event_type 不正确：{event_type}")
            continue
        if event.get("category") != EVENT_CATEGORIES[event_type]:
            errors.append(f"日历事件 {event_id} 的 category 与类型不匹配")
        if event.get("priority") not in PRIORITIES:
            errors.append(f"日历事件 {event_id} 的 priority 不正确")
        if event.get("status") not in EVENT_STATUSES:
            errors.append(f"日历事件 {event_id} 的 status 不正确")

        event_date = _parse_date(event.get("date"))
        remind_date = _parse_date(event.get("remind_date"))
        remind_days = event.get("remind_days_before")
        if event_date is None:
            errors.append(f"日历事件 {event_id} 的日期必须是 YYYY-MM-DD")
        if not _is_non_negative_int(remind_days):
            errors.append(f"日历事件 {event_id} 的 remind_days_before 必须是非负整数")
        elif event_date is not None:
            expected = event_date - timedelta(days=remind_days)
            if remind_date != expected:
                errors.append(
                    f"日历事件 {event_id} 的提醒日期应为 {expected.isoformat()}"
                )

        budget = event.get("budget")
        if budget is not None and (not _is_finite_number(budget) or budget < 0):
            errors.append(f"日历事件 {event_id} 的预算必须是非负数字")

        if event_type == "birthday" and event.get("related_member_id") not in family_ids:
            errors.append(f"日历事件 {event_id} 引用了不存在的家庭成员")
        if event_type == "bill_due" and event.get("related_card_id") not in card_ids:
            errors.append(f"日历事件 {event_id} 引用了不存在的卡片")
        if event_type == "subscription_renewal":
            if event.get("related_subscription_id") not in subscription_ids:
                errors.append(f"日历事件 {event_id} 引用了不存在的订阅")

    return result


def _validate_insights(
    insights: Any,
    transaction_ids: set,
    event_ids: set,
    card_ids: set,
    errors: List[str],
) -> None:
    """检查智能检测标签（证据必须指向真实交易）。"""
    if insights is None:
        return
    if not isinstance(insights, list):
        errors.append("expected_insights 必须是列表")
        return

    seen = set()
    for insight in insights:
        if not isinstance(insight, dict):
            errors.append("智能洞察格式错误")
            continue
        insight_id = insight.get("insight_id")
        if insight_id in seen:
            errors.append(f"智能洞察 ID 重复：{insight_id}")
        seen.add(insight_id)

        insight_type = insight.get("insight_type")
        if insight_type not in INSIGHT_TYPES:
            errors.append(f"智能洞察 {insight_id} 的类型不正确：{insight_type}")
        if insight.get("severity") not in SEVERITIES:
            errors.append(f"智能洞察 {insight_id} 的 severity 不正确")
        if _parse_date(insight.get("date")) is None:
            errors.append(f"智能洞察 {insight_id} 的日期必须是 YYYY-MM-DD")
        if not isinstance(insight.get("title"), str) or not insight.get("title"):
            errors.append(f"智能洞察 {insight_id} 缺少 title")

        evidence = insight.get("evidence_transaction_ids")
        if not isinstance(evidence, list):
            errors.append(f"智能洞察 {insight_id} 的 evidence_transaction_ids 必须是列表")
            evidence = []
        for transaction_id in evidence:
            if transaction_id not in transaction_ids:
                errors.append(f"智能洞察 {insight_id} 引用了不存在的交易：{transaction_id}")
        if insight_type == "duplicate_charge" and len(evidence) < 2:
            errors.append(f"智能洞察 {insight_id}：重复扣款至少需要 2 笔证据交易")

        related_event = insight.get("related_event_id")
        if related_event is not None and related_event not in event_ids:
            errors.append(f"智能洞察 {insight_id} 关联的日历事件不存在：{related_event}")
        related_card = insight.get("related_card_id")
        if related_card is not None and related_card not in card_ids:
            errors.append(f"智能洞察 {insight_id} 关联的卡片不存在：{related_card}")


def _validate_card_events(
    events: Any,
    cards_by_id: Dict[str, Dict[str, Any]],
    errors: List[str],
) -> None:
    """检查卡片事件，并确认卡片最终状态与最后一条事件一致。"""
    if events is None:
        return
    if not isinstance(events, list):
        errors.append("card_events 必须是列表")
        return

    final_status: Dict[str, str] = {}
    final_credit_limit: Dict[str, float] = {}
    final_transaction_limit: Dict[str, Dict[str, Any]] = {}

    for event in events:
        if not isinstance(event, dict):
            errors.append("卡片事件格式错误")
            continue
        event_id = event.get("event_id")
        card_id = event.get("card_id")
        card = cards_by_id.get(card_id)
        if card is None:
            errors.append(f"卡片事件 {event_id} 引用了不存在的卡片：{card_id}")
            continue
        event_type = event.get("event_type")
        if event_type not in CARD_EVENT_TYPES:
            errors.append(f"卡片事件 {event_id} 的类型不正确：{event_type}")
        if _parse_date(event.get("date")) is None:
            errors.append(f"卡片事件 {event_id} 的日期必须是 YYYY-MM-DD")
        if event.get("status") != "completed":
            errors.append(f"卡片事件 {event_id} 必须是已完成事件")
        before = event.get("before")
        after = event.get("after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            errors.append(f"卡片事件 {event_id} 必须包含 before 和 after 快照")
            continue

        if event_type == "limit_adjusted":
            old_limit = before.get("credit_limit")
            new_limit = after.get("credit_limit")
            if not _is_finite_number(old_limit) or not _is_finite_number(new_limit) or new_limit < 0:
                errors.append(f"卡片事件 {event_id} 的额度前后值必须是数字")
            elif abs(old_limit - new_limit) <= 0.01:
                errors.append(f"卡片事件 {event_id} 的调额前后金额相同")
            else:
                final_credit_limit[card_id] = new_limit
        if event_type == "transaction_limit_set":
            limits = after.get("transaction_limit")
            if not isinstance(limits, dict):
                errors.append(f"卡片事件 {event_id} 缺少新的 transaction_limit")
            else:
                final_transaction_limit[card_id] = limits
        if "status" in after:
            final_status[card_id] = after["status"]

    for card_id, status in final_status.items():
        card = cards_by_id.get(card_id)
        if card is not None and card.get("status") != status:
            errors.append(
                f"卡片 {card_id} 的最终状态 {card.get('status')} 与最后一条事件 {status} 不一致"
            )
    for card_id, limit in final_credit_limit.items():
        card = cards_by_id.get(card_id)
        if card is not None and _is_finite_number(card.get("credit_limit")):
            if abs(card["credit_limit"] - limit) > 0.01:
                errors.append(f"卡片 {card_id} 的额度与最后一条调额事件不一致")
    for card_id, limits in final_transaction_limit.items():
        card = cards_by_id.get(card_id)
        if card is not None and card.get("transaction_limit") != limits:
            errors.append(f"卡片 {card_id} 的交易限额与最后一条事件不一致")


# ---------------------------------------------------------------------------
# 3. 场景专项校验（A~G）
# ---------------------------------------------------------------------------

def _check_scenario_a(has_income: bool, has_expense: bool, errors: List[str]) -> None:
    """场景 A：普通银行用户，必须同时有收入和支出。"""
    if not has_income:
        errors.append("普通用户场景缺少收入交易")
    if not has_expense:
        errors.append("普通用户场景缺少支出交易")


def _check_scenario_b(
    transactions: List[Dict[str, Any]],
    config: Dict[str, Any],
    errors: List[str],
) -> None:
    """场景 B：按真实流水汇总购物支出，验证有两个连续月份且差额等于配置值。"""
    shopping_by_month: Dict[str, float] = {}

    for transaction in transactions:
        if (
            transaction.get("category") != "购物"
            or transaction.get("transaction_type") != "expense"
            or transaction.get("status", "completed") != "completed"
        ):
            continue
        transaction_id = transaction.get("transaction_id")
        date_value = transaction.get("date")
        amount = transaction.get("amount")

        if _parse_date(date_value) is None:
            errors.append(f"场景B：交易 {transaction_id} 日期格式必须为 YYYY-MM-DD")
            continue
        if _is_finite_number(amount):
            month_key = date_value[:7]
            shopping_by_month[month_key] = shopping_by_month.get(month_key, 0.0) + amount

    months = sorted(shopping_by_month)
    if len(months) != 2:
        errors.append(f"场景B：应恰有连续两个月的购物支出，实际检测到 {len(months)} 个月")
        return

    first_year, first_month = (int(part) for part in months[0].split("-"))
    second_year, second_month = (int(part) for part in months[1].split("-"))
    consecutive = _month_index(second_year, second_month) == _month_index(first_year, first_month) + 1
    if not consecutive:
        errors.append(f"场景B：购物支出月份 {months[0]} 和 {months[1]} 不连续")

    expected = config.get("params", {}).get("increase_amount", 800.0)
    if _is_finite_number(expected):
        actual = round(shopping_by_month[months[1]] - shopping_by_month[months[0]], 2)
        if abs(actual - round(expected, 2)) > 0.01:
            errors.append(
                f"场景B：购物支出差额实际为 {actual} 元，要求为 {round(expected, 2)} 元"
            )
    else:
        errors.append("场景B：配置中的 increase_amount 必须是有限数字")


def _check_scenario_c(
    transactions: List[Dict[str, Any]],
    transaction_ids: set,
    errors: List[str],
) -> None:
    """场景 C：疑似重复扣款。

    规则：
    1. 至少保留一笔正常交易（非疑似）；
    2. 疑似交易必须通过 duplicate_group_id 归组，每组至少 2 笔；
    3. 组内交易商户、金额、类别、日期、账户完全一致；
    4. 组内交易都是已完成的支出，且通过 related_transaction_id 互相引用；
    5. 不删除原始交易（每笔都还在流水里，且状态不是 reversed）。
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    has_normal_transaction = False

    for transaction in transactions:
        if not transaction.get("is_suspicious"):
            has_normal_transaction = True
        group_id = transaction.get("duplicate_group_id")
        if group_id:
            groups.setdefault(group_id, []).append(transaction)
        elif transaction.get("is_suspicious"):
            errors.append(
                f"场景C：疑似交易 {transaction.get('transaction_id')} 缺少 duplicate_group_id"
            )

    if not groups:
        errors.append("场景C：未找到疑似重复扣款组")
    if not has_normal_transaction:
        errors.append("场景C：未保留原始正常交易")

    for group_id, members in groups.items():
        if len(members) < 2:
            errors.append(f"场景C：重复组 {group_id} 成员不足 2 笔")
            continue

        for field, label in (
            ("merchant", "商户"),
            ("amount", "金额"),
            ("category", "类别"),
            ("date", "日期"),
            ("account_id", "账户"),
        ):
            values = {member.get(field) for member in members}
            if len(values) != 1:
                errors.append(f"场景C：重复组 {group_id} 的{label}不一致，不满足重复扣款条件")

        member_ids = {member.get("transaction_id") for member in members}

        for member in members:
            member_id = member.get("transaction_id")
            if member.get("transaction_type") != "expense":
                errors.append(f"场景C：重复组 {group_id} 中的交易 {member_id} 不是支出")
            if member.get("status", "completed") != "completed":
                errors.append(
                    f"场景C：重复组 {group_id} 中的交易 {member_id} 状态为 "
                    f"{member.get('status')}，疑似重复扣款应是已完成交易"
                )

            related = member.get("related_transaction_id")
            if not related:
                errors.append(f"场景C：交易 {member_id} 缺少 related_transaction_id")
            elif related not in transaction_ids:
                errors.append(f"场景C：交易 {member_id} 关联的交易不存在：{related}")
            elif related == member_id:
                errors.append(f"场景C：交易 {member_id} 不能关联自己")
            elif related not in member_ids:
                errors.append(f"场景C：交易 {member_id} 关联的交易不在同一重复组")
            elif len(members) == 2:
                # 两笔一组时，要求双向关联，主 Agent 才能顺着链条找到"另一笔"
                partner = next(m for m in members if m.get("transaction_id") == related)
                if partner.get("related_transaction_id") != member_id:
                    errors.append(f"场景C：交易 {member_id} 与 {related} 的关联不对称")


def _check_scenario_d(
    transactions: List[Dict[str, Any]],
    accounts: List[Dict[str, Any]],
    errors: List[str],
) -> None:
    """场景 D：余额不足。

    规则：
    1. 至少有一笔被拒绝的转账请求；
    2. 该请求是 transfer_out，金额大于该账户当前可用余额（余额未扣减，所以等于期末余额）；
    3. 被拒绝的交易不允许计入余额（对账已覆盖），且账户不出现负余额。
    """
    accounts_by_id = {account.get("account_id"): account for account in accounts}
    rejected = [
        transaction
        for transaction in transactions
        if transaction.get("status") == "rejected"
        or transaction.get("expected_result") == "rejected"
    ]

    if not rejected:
        errors.append("场景D：缺少被拒绝的转账请求")
        return

    for transaction in rejected:
        transaction_id = transaction.get("transaction_id")
        if transaction.get("transaction_type") != "transfer_out":
            errors.append(f"场景D：被拒绝的交易 {transaction_id} 不是转出转账")

        account = accounts_by_id.get(transaction.get("account_id"))
        amount = transaction.get("amount")
        if account is None or not _is_finite_number(amount):
            continue
        available = account.get("balance")
        if not _is_finite_number(available):
            continue
        if amount <= available:
            errors.append(
                f"场景D：转账请求 {transaction_id} 金额 {amount} 未超过可用余额 {available}"
            )

    for account in accounts:
        balance = account.get("balance")
        if _is_finite_number(balance) and balance < 0:
            errors.append(f"场景D：账户 {account.get('account_id')} 出现负余额")


def _check_scenario_e(
    transactions: List[Dict[str, Any]],
    errors: List[str],
) -> None:
    """场景 E：周期性订阅。

    规则：
    1. 至少 2 期订阅扣款，且都是已完成的支出；
    2. 每期商户、金额、类别一致，类别为"订阅"；
    3. 覆盖至少两个连续月份；
    4. 每月扣款日期一致（2 月等短月份允许顺延到当月最后一天）。
    """
    subscriptions = [
        transaction
        for transaction in transactions
        if transaction.get("category") == "订阅"
        or transaction.get("recurring")
        or transaction.get("subscription_type")
    ]

    if len(subscriptions) < 2:
        errors.append("场景E：周期订阅扣款不足 2 期")
        return

    amounts = {transaction.get("amount") for transaction in subscriptions}
    merchants = {transaction.get("merchant") for transaction in subscriptions}
    categories = {transaction.get("category") for transaction in subscriptions}
    dates = [_parse_date(transaction.get("date")) for transaction in subscriptions]

    if len(amounts) != 1:
        errors.append("场景E：订阅扣款金额不一致（应为固定金额）")
    if len(merchants) != 1:
        errors.append("场景E：订阅扣款商户不一致")
    if "订阅" not in categories:
        errors.append("场景E：订阅扣款缺少'订阅'类别")

    for transaction, parsed in zip(subscriptions, dates):
        transaction_id = transaction.get("transaction_id")
        if transaction.get("transaction_type") != "expense":
            errors.append(f"场景E：订阅扣款 {transaction_id} 不是支出")
        if transaction.get("status", "completed") != "completed":
            errors.append(f"场景E：订阅扣款 {transaction_id} 不是已完成交易")
        if not _is_finite_number(transaction.get("amount")) or transaction.get("amount") <= 0:
            errors.append(f"场景E：订阅扣款 {transaction_id} 的金额必须大于 0")
        if parsed is None:
            errors.append(f"场景E：订阅扣款 {transaction_id} 的日期格式必须为 YYYY-MM-DD")
    if any(parsed is None for parsed in dates):
        return

    months = sorted({date_cls(parsed.year, parsed.month, 1) for parsed in dates})
    if len(months) < 2:
        errors.append("场景E：订阅扣款未覆盖多个月份")
    else:
        for earlier, later in zip(months, months[1:]):
            if _month_index(later.year, later.month) != _month_index(earlier.year, earlier.month) + 1:
                errors.append(
                    f"场景E：订阅扣款月份 {earlier:%Y-%m} 与 {later:%Y-%m} 不连续"
                )
                break

    days = {parsed.day for parsed in dates}
    target_day = max(days)
    for parsed in dates:
        last_day = (date_cls(parsed.year + (parsed.month == 12), parsed.month % 12 + 1, 1)
                    - timedelta(days=1)).day
        if parsed.day != min(target_day, last_day):
            errors.append("场景E：订阅扣款日期不是每月同一天（短月份应顺延到当月最后一天）")
            break


def _check_scenario_f(scenario: Dict[str, Any], errors: List[str]) -> None:
    """场景 F：跨场景联动的家庭生日活动。

    规则：
    1. family 至少有一位家庭成员，生日是合法日期；
    2. 生日所在月份 = budget.lock_month；
    3. 锁定金额大于 0 且不超过当月活动预算；
    4. activity_calendar 覆盖生日前 2 天的鲜花与蛋糕订购；
    5. 日历里所有未取消事项的预算合计不超过锁定金额。
    """
    family = scenario.get("family")
    budget = scenario.get("budget")
    calendar = scenario.get("activity_calendar")

    if not isinstance(family, list) or not family:
        errors.append("场景F：family 必须是非空列表")
        family = []

    budget_amount = None
    locked_amount = None
    lock_month = None

    if not isinstance(budget, dict):
        errors.append("场景F：缺少 budget 预算信息")
    else:
        budget_amount = budget.get("monthly_activity_budget")
        locked_amount = budget.get("locked_amount")
        lock_month = budget.get("lock_month")

        if not _is_finite_number(budget_amount) or budget_amount <= 0:
            errors.append("场景F：monthly_activity_budget 必须是大于 0 的数字")
            budget_amount = None
        if not _is_finite_number(locked_amount) or locked_amount <= 0:
            errors.append("场景F：locked_amount 必须是大于 0 的数字")
            locked_amount = None
        if _parse_month(lock_month) is None:
            errors.append("场景F：budget.lock_month 必须是 YYYY-MM 格式")
            lock_month = None
        if budget_amount is not None and locked_amount is not None and locked_amount > budget_amount:
            errors.append("场景F：锁定金额不能超过当月活动预算")

    birthdays: List[Tuple[str, date_cls]] = []
    for member in family:
        if not isinstance(member, dict):
            errors.append("场景F：家庭成员信息格式错误")
            continue
        member_id = member.get("member_id")
        if not member_id:
            errors.append("场景F：家庭成员缺少 member_id")
        birthday = _parse_date(member.get("birthday"))
        if birthday is None:
            errors.append(f"场景F：家庭成员 {member_id} 的生日必须是 YYYY-MM-DD 格式")
            continue
        birthdays.append((member_id, birthday))
        if lock_month is not None and f"{birthday.year:04d}-{birthday.month:02d}" != lock_month:
            errors.append(
                f"场景F：家庭成员 {member_id} 的生日 {birthday.isoformat()} 不在锁定月份 {lock_month}"
            )

    if not isinstance(calendar, list) or not calendar:
        errors.append("场景F：activity_calendar 必须是非空列表")
        return

    planned_total = 0.0
    calendar_dates: Dict[str, set] = {}

    for entry in calendar:
        if not isinstance(entry, dict):
            errors.append("场景F：活动日历条目格式错误")
            continue
        entry_date = _parse_date(entry.get("date"))
        if entry_date is None:
            errors.append("场景F：活动日历条目日期必须是 YYYY-MM-DD 格式")
            continue
        if not isinstance(entry.get("title"), str) or not entry.get("title").strip():
            errors.append(f"场景F：{entry_date.isoformat()} 的活动缺少 title")
        value = entry.get("budget")
        if not _is_finite_number(value) or value < 0:
            errors.append(f"场景F：{entry_date.isoformat()} 的活动预算必须是非负数字")
            value = 0.0
        if entry.get("status") != "cancelled":
            planned_total += value
        calendar_dates.setdefault(entry.get("category", ""), set()).add(entry_date)

    for member_id, birthday in birthdays:
        order_date = birthday - timedelta(days=2)
        for category, label in (("鲜花", "鲜花"), ("蛋糕", "蛋糕")):
            if order_date not in calendar_dates.get(category, set()):
                errors.append(
                    f"场景F：家庭成员 {member_id} 生日前 2 天（{order_date.isoformat()}）"
                    f"缺少{label}订购安排"
                )

    if locked_amount is not None and planned_total > locked_amount + 0.01:
        errors.append(
            f"场景F：活动日历预算合计 {round(planned_total, 2)} 超过锁定金额 {locked_amount}"
        )

    balances = [
        account.get("balance")
        for account in scenario.get("accounts", [])
        if _is_finite_number(account.get("balance"))
    ]
    if locked_amount is not None and balances and locked_amount > max(balances) + 0.01:
        errors.append(
            f"场景F：锁定金额 {locked_amount} 超过账户可用余额 {max(balances)}"
        )


def _check_scenario_g(
    scenario: Dict[str, Any],
    cards_by_id: Dict[str, Dict[str, Any]],
    calendar_by_id: Dict[str, Dict[str, Any]],
    errors: List[str],
) -> None:
    """场景 G：卡片管理。

    规则：
    1. 至少一张借记卡和一张信用卡；
    2. 必须有信用卡账单，且账单已通过通用校验；
    3. 必须有卡片管理事件（挂失/冻结/额度调整/交易限额/补卡）；
    4. 有未还账单时，日历里必须有对应的还款提醒。
    """
    card_types = {card.get("card_type") for card in cards_by_id.values()}
    if "debit" not in card_types:
        errors.append("场景G：缺少借记卡")
    if "credit" not in card_types:
        errors.append("场景G：缺少信用卡")

    bill = scenario.get("credit_card_bill")
    if not isinstance(bill, dict):
        errors.append("场景G：缺少信用卡账单")
    elif bill.get("outstanding_amount", 0) > 0 and calendar_by_id:
        card_id = bill.get("card_id")
        has_due_reminder = any(
            event.get("event_type") == "bill_due" and event.get("related_card_id") == card_id
            for event in calendar_by_id.values()
        )
        if not has_due_reminder:
            errors.append("场景G：缺少信用卡还款提醒")

    if not scenario.get("card_events"):
        errors.append("场景G：缺少卡片管理事件")


# ---------------------------------------------------------------------------
# 3. 对外入口
# ---------------------------------------------------------------------------

def validate(
    scenario: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """检查银行场景的基本结构和数据合理性。

    返回 (是否通过, 消息列表)。消息列表为空表示完全通过。
    """
    errors: List[str] = []

    # 1. 场景本身
    if not isinstance(scenario, dict):
        return False, ["场景数据不是有效的字典"]
    if not scenario:
        return False, ["场景数据为空"]

    # 2. 必要字段（缺了就停止后续检查，避免连锁报错）
    missing = [field for field in REQUIRED_FIELDS if field not in scenario]
    if missing:
        return False, [f"缺少必要字段：{field}" for field in missing]

    # 3. 用户 / 账户 / 交易
    _validate_user(scenario["user"], errors)
    accounts = _validate_accounts(scenario["accounts"], errors)
    account_ids = {account.get("account_id") for account in accounts}

    transactions, transaction_ids, has_income, has_expense = _validate_transactions(
        scenario["transactions"], account_ids, errors
    )

    # 4. 账户对账
    _check_balance_reconciliation(accounts, transactions, errors)

    # 5. 生活层通用校验（卡片、账单、家庭、订阅、日历、洞察、卡片事件）
    cards_by_id = _validate_cards(scenario.get("cards"), account_ids, errors)
    _validate_credit_card_bill(scenario.get("credit_card_bill"), cards_by_id, errors)
    members_by_id = _validate_family(scenario.get("family"), errors)
    subscriptions_by_id = _validate_subscriptions(
        scenario.get("subscriptions"), transactions, errors
    )
    calendar_by_id = _validate_calendar_events(
        scenario.get("calendar_events"),
        set(members_by_id),
        set(cards_by_id),
        set(subscriptions_by_id),
        errors,
    )
    _validate_card_events(scenario.get("card_events"), cards_by_id, errors)

    bill_items = (scenario.get("credit_card_bill") or {}).get("items") or []
    all_transaction_ids = set(transaction_ids) | {
        item.get("transaction_id") for item in bill_items if isinstance(item, dict)
    }
    _validate_insights(
        scenario.get("expected_insights"),
        all_transaction_ids,
        set(calendar_by_id),
        set(cards_by_id),
        errors,
    )

    # 6. 场景专项校验
    scenario_type = scenario.get("scenario_type")

    if scenario_type == "A":
        _check_scenario_a(has_income, has_expense, errors)
    elif scenario_type == "B":
        _check_scenario_b(transactions, config, errors)
    elif scenario_type == "C":
        _check_scenario_c(transactions, transaction_ids, errors)
    elif scenario_type == "D":
        _check_scenario_d(transactions, accounts, errors)
    elif scenario_type == "E":
        _check_scenario_e(transactions, errors)
    elif scenario_type == "F":
        _check_scenario_f(scenario, errors)
    elif scenario_type == "G":
        _check_scenario_g(scenario, cards_by_id, calendar_by_id, errors)
    else:
        errors.append(f"不支持的场景类型：{scenario_type}")

    return len(errors) == 0, errors
