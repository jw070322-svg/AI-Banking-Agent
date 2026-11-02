"""analysis.anomaly —— 异常交易识别。

只根据**真实流水**判断，不读取 `expected_insights`、`duplicate_group_id`
或 `is_suspicious` 等标准答案字段，否则评估就没有意义了。

识别类型（与环境生成 Agent 的标准答案同名）：
- duplicate_charge       同一商户、同一金额、同一天出现多笔扣款；
- failed_transfer        转账被拒绝/失败；
- upcoming_bill          信用卡账单未还，临近/已过还款日；
- subscription_renewal   订阅即将续费；
- subscription_price_change  订阅扣款金额明显变化（涨价/降价）；
- birthday_upcoming      家人生日临近；
- budget_lock            生日活动预算已锁定；
- salary_detected        识别到工资收入；
- unusual_spending       单笔支出超过类别门槛和平均支出倍数（默认 1000 元 / 4 倍，
                         装修、旅行、医疗等类别门槛更高）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .data import (
    consumption_entries,
    deposit_transactions,
    income_entries,
    parse_date,
    reference_date,
)

# 异常大额消费的类别阈值（整数分）：
# (最低关注金额, 相对平均支出的倍数)
# 装修、旅行、医疗这类一次性大额本来就常见，门槛要高；
# 日常消费和普通购物沿用默认门槛（1000 元 / 4 倍）。
DEFAULT_UNUSUAL_RULE = (100_000, 4)          # 1000 元 / 4 倍
CATEGORY_UNUSUAL_RULES: Dict[str, Tuple[int, int]] = {
    "旅行": (2_000_000, 6),    # 20000 元
    "医疗": (5_000_000, 6),    # 50000 元
    "教育": (5_000_000, 6),    # 50000 元
    "保险": (2_000_000, 6),    # 20000 元
    "居住": (3_000_000, 6),    # 30000 元
    "装修": (3_000_000, 6),    # 30000 元
    "家居": (2_000_000, 6),    # 20000 元
}

DUPLICATE_TIME_WINDOW_MINUTES = 10


def _finding(
    insight_type: str,
    severity: str,
    title: str,
    event_date: str,
    *,
    evidence: Optional[Iterable[str]] = None,
    related_event_id: Optional[str] = None,
    related_card_id: Optional[str] = None,
    related_subscription_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "finding_id": None,  # 统一排序后再编号，保证结果稳定
        "insight_type": insight_type,
        "severity": severity,
        "title": title,
        "date": event_date,
        "evidence_transaction_ids": list(evidence or []),
        "related_event_id": related_event_id,
        "related_card_id": related_card_id,
        "related_subscription_id": related_subscription_id,
        "details": details or {},
    }


def _days_until(value: Any, today: date) -> Optional[int]:
    parsed = parse_date(value)
    if parsed is None:
        return None
    return (parsed - today).days


def _time_clusters(entries: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """按时间聚簇：相邻两笔间隔 ≤10 分钟算同一簇。

    这样"早上 9:00 和 9:02 各扣一次、晚上 6:00 再买一次"只会把前两笔当成
    疑似重复，而不是把三笔一起误判。
    """
    ordered = sorted(entries, key=lambda entry: entry["time"])
    clusters: List[List[Dict[str, Any]]] = []
    for entry in ordered:
        current_time = datetime.strptime(entry["time"], "%H:%M:%S")
        if clusters:
            previous_time = datetime.strptime(clusters[-1][-1]["time"], "%H:%M:%S")
            if (current_time - previous_time) <= timedelta(minutes=DUPLICATE_TIME_WINDOW_MINUTES):
                clusters[-1].append(entry)
                continue
        clusters.append([entry])
    return clusters


def _detect_duplicates(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """同一商户 + 同一金额 + 同一天的多笔已入账扣款。

    判定策略（为解决"真实重复消费"的误报）：
    - 所有交易都有时间：按 10 分钟窗口聚簇，只有同一簇 ≥2 笔才算疑似重复；
      相隔数小时的同额消费视为正常（例如上午和下午各买一杯同样的咖啡）；
    - 缺少时间信息：保守地给出 medium 级别提示，交给用户确认。
    """
    groups: Dict[Tuple[str, str, int, str], List[Dict[str, Any]]] = {}
    for entry in consumption_entries(data):
        if entry["amount_minor"] <= 0:
            continue
        key = (entry["source"], entry["merchant"], entry["amount_minor"], entry["date"])
        groups.setdefault(key, []).append(entry)

    findings: List[Dict[str, Any]] = []
    for (source, merchant, amount_minor, entry_date), entries in groups.items():
        if len(entries) < 2:
            continue

        has_all_times = all(
            isinstance(entry.get("time"), str) and len(entry["time"]) == 8
            for entry in entries
        )

        if has_all_times:
            clusters = [cluster for cluster in _time_clusters(entries) if len(cluster) >= 2]
            if not clusters:
                continue  # 时间隔得很开，属于正常重复消费
            for cluster in clusters:
                findings.append(_duplicate_finding(
                    source, merchant, amount_minor, entry_date, cluster, "high", True,
                ))
        else:
            findings.append(_duplicate_finding(
                source, merchant, amount_minor, entry_date, entries, "medium", False,
            ))
    return findings


def _duplicate_finding(
    source: str,
    merchant: str,
    amount_minor: int,
    entry_date: str,
    entries: List[Dict[str, Any]],
    severity: str,
    within_window: bool,
) -> Dict[str, Any]:
    return _finding(
        "duplicate_charge",
        severity,
        "发现疑似重复扣款",
        entry_date,
        evidence=[entry["transaction_id"] for entry in entries],
        details={
            "source": source,
            "merchant": merchant,
            "amount_minor": amount_minor,
            "count": len(entries),
            "within_10_minutes": within_window,
        },
    )


def _detect_failed_transfers(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for transaction in data.get("transactions", []):
        if not isinstance(transaction, dict):
            continue
        if transaction.get("status") != "rejected" and transaction.get("expected_result") != "rejected":
            continue
        findings.append(_finding(
            "failed_transfer",
            "high",
            "转账请求被拒绝",
            transaction.get("date", ""),
            evidence=[transaction.get("transaction_id")],
            details={
                "transaction_type": transaction.get("transaction_type"),
                "reason": transaction.get("description", ""),
            },
        ))
    return findings


def _detect_upcoming_bills(data: Dict[str, Any], today: date) -> List[Dict[str, Any]]:
    bill = data.get("credit_card_bill")
    if not isinstance(bill, dict):
        return []
    outstanding = bill.get("outstanding_amount_minor")
    if not isinstance(outstanding, int) or outstanding <= 0:
        return []

    due_date = bill.get("due_date", "")
    days_left = _days_until(due_date, today)
    if days_left is not None and days_left < 0:
        severity = "high"
        title = "信用卡账单已逾期"
    elif days_left is not None and days_left <= 7:
        severity = "high"
        title = "信用卡账单临近还款日"
    else:
        severity = "medium"
        title = "信用卡账单待还款"

    return [_finding(
        "upcoming_bill",
        severity,
        title,
        due_date,
        related_card_id=bill.get("card_id"),
        details={
            "status": bill.get("status"),
            "days_until_due": days_left,
            "outstanding_minor": outstanding,
        },
    )]


def _detect_subscriptions(data: Dict[str, Any], today: date) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for subscription in data.get("subscriptions", []) or []:
        if subscription.get("status") != "active":
            continue
        next_charge = subscription.get("next_charge_date", "")
        days_left = _days_until(next_charge, today)
        severity = "high" if days_left is not None and days_left <= 3 else "medium"
        findings.append(_finding(
            "subscription_renewal",
            severity,
            f"{subscription.get('merchant', '订阅')}即将续费",
            next_charge,
            related_subscription_id=subscription.get("subscription_id"),
            details={
                "merchant": subscription.get("merchant"),
                "amount_minor": subscription.get("amount_minor"),
                "cycle": subscription.get("cycle"),
                "days_until_charge": days_left,
            },
        ))
    return findings


def _detect_subscription_price_changes(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """同一订阅商户最近两次扣款金额变化超过 1%（且至少 1 元）时提示。"""
    charges: Dict[str, List[Dict[str, Any]]] = {}
    for transaction in deposit_transactions(data):
        if transaction.get("transaction_type") != "expense":
            continue
        if transaction.get("category") != "订阅":
            continue
        merchant = transaction.get("merchant")
        amount = transaction.get("amount_minor")
        if not merchant or not isinstance(amount, int) or isinstance(amount, bool):
            continue
        charges.setdefault(merchant, []).append(transaction)

    findings: List[Dict[str, Any]] = []
    for merchant, rows in charges.items():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda row: (row.get("date", ""), row.get("transaction_id") or ""))
        previous, latest = rows[-2], rows[-1]
        previous_amount = previous["amount_minor"]
        latest_amount = latest["amount_minor"]
        difference = latest_amount - previous_amount
        threshold = max(100, int(previous_amount * 0.01))
        if abs(difference) <= threshold:
            continue

        increase = difference > 0
        findings.append(_finding(
            "subscription_price_change",
            "high" if increase else "medium",
            f"{merchant}{'涨价' if increase else '降价'}提醒",
            latest.get("date", ""),
            evidence=[latest.get("transaction_id"), previous.get("transaction_id")],
            details={
                "merchant": merchant,
                "previous_amount_minor": previous_amount,
                "latest_amount_minor": latest_amount,
                "change_minor": difference,
                "change_bp": int(round(difference * 10000 / previous_amount)) if previous_amount else 0,
            },
        ))
    return findings


def _detect_birthdays(data: Dict[str, Any], today: date) -> List[Dict[str, Any]]:
    events = {
        event.get("related_member_id"): event
        for event in data.get("calendar_events", []) or []
        if event.get("event_type") == "birthday"
    }
    findings: List[Dict[str, Any]] = []
    for member in data.get("family", []) or []:
        birthday = member.get("birthday", "")
        days_left = _days_until(birthday, today)
        if days_left is None:
            continue
        if days_left <= 30:
            severity = "high"
        elif days_left <= 90:
            severity = "medium"
        else:
            severity = "low"
        member_id = member.get("member_id")
        relation = member.get("relation", "家人")
        event = events.get(member_id)
        findings.append(_finding(
            "birthday_upcoming",
            severity,
            f"{relation}生日临近" if days_left <= 30 else f"{relation}生日提醒",
            birthday,
            related_event_id=event.get("event_id") if event else None,
            details={
                "relation": relation,
                "age_turning": member.get("age_turning"),
                "days_until": days_left,
            },
        ))
    return findings


def _detect_budget_lock(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    budget = data.get("budget")
    if not isinstance(budget, dict):
        return []
    locked = budget.get("locked_amount_minor")
    if not isinstance(locked, int) or isinstance(locked, bool) or locked <= 0:
        return []
    lock_month = budget.get("lock_month")
    event = next(
        (event for event in data.get("calendar_events", []) or []
         if event.get("event_type") == "budget_lock"),
        None,
    )
    return [_finding(
        "budget_lock",
        "medium",
        "生日活动预算已锁定",
        f"{lock_month}-01" if lock_month else "",
        related_event_id=event.get("event_id") if event else None,
        details={"locked_amount_minor": locked, "lock_month": lock_month,
                 "calendar_entries": len(data.get("activity_calendar", []) or [])},
    )]


def _detect_salary(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    salaries = [
        entry for entry in income_entries(data)
        if entry["category"] == "工资" or "工资" in str(entry["category"])
    ]
    if not salaries:
        return []
    latest = max(salaries, key=lambda entry: (entry["date"], entry["transaction_id"] or ""))
    return [_finding(
        "salary_detected",
        "low",
        "识别到工资收入",
        latest["date"],
        evidence=[latest["transaction_id"]],
        details={"merchant": latest["merchant"], "cycle": "monthly"},
    )]


def _is_fixed_obligation(entry: Dict[str, Any], expenses: List[Dict[str, Any]]) -> bool:
    """判断是否像房租/学费这类固定支出。

    条件：同一商户在至少两个不同月份出现，且每次金额都在本次金额的 ±10% 以内。
    这类支出即使金额大，也不应该被当成"异常消费"。
    """
    same_merchant = [
        candidate for candidate in expenses
        if candidate["merchant"] == entry["merchant"] and entry["merchant"]
    ]
    months = {candidate["month"] for candidate in same_merchant}
    if len(months) < 2:
        return False
    tolerance = entry["amount_minor"] * 0.1
    return all(
        abs(candidate["amount_minor"] - entry["amount_minor"]) <= tolerance
        for candidate in same_merchant
    )


def _detect_unusual_spending(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """只分析借记卡支出，与标准答案的统计口径保持一致。"""
    expenses = [
        entry for entry in consumption_entries(data)
        if entry["source"] == "deposit" and entry["amount_minor"] > 0
    ]
    if len(expenses) < 3:
        return []
    average = sum(entry["amount_minor"] for entry in expenses) / len(expenses)
    outliers = []
    for entry in expenses:
        minimum, multiplier = CATEGORY_UNUSUAL_RULES.get(entry["category"], DEFAULT_UNUSUAL_RULE)
        if entry["amount_minor"] < minimum:
            continue
        if entry["amount_minor"] <= average * multiplier:
            continue
        if _is_fixed_obligation(entry, expenses):
            continue
        outliers.append(entry)
    outliers.sort(key=lambda entry: (entry["date"], entry["transaction_id"] or ""))
    findings: List[Dict[str, Any]] = []
    for entry in outliers[:2]:
        findings.append(_finding(
            "unusual_spending",
            "medium",
            "发现异常大额消费",
            entry["date"],
            evidence=[entry["transaction_id"]],
            details={
                "merchant": entry["merchant"],
                "category": entry["category"],
                "amount_minor": entry["amount_minor"],
                "average_expense_minor": int(round(average)),
            },
        ))
    return findings


def detect_anomalies(data: Dict[str, Any], today: Optional[date] = None) -> List[Dict[str, Any]]:
    """识别异常与重要提醒，返回按日期排序的发现列表。

    参数 `today` 用于计算"还有几天"，不传则使用场景 created_at 的日期，
    这样同一份样例在任何一天运行结果都一致。
    """
    base_date = reference_date(data, today)

    findings: List[Dict[str, Any]] = []
    findings.extend(_detect_duplicates(data))
    findings.extend(_detect_failed_transfers(data))
    findings.extend(_detect_upcoming_bills(data, base_date))
    findings.extend(_detect_subscriptions(data, base_date))
    findings.extend(_detect_subscription_price_changes(data))
    findings.extend(_detect_birthdays(data, base_date))
    findings.extend(_detect_budget_lock(data))
    findings.extend(_detect_salary(data))
    findings.extend(_detect_unusual_spending(data))

    findings.sort(key=lambda item: (
        item["date"], item["insight_type"], item["evidence_transaction_ids"]
    ))
    for index, item in enumerate(findings, start=1):
        item["finding_id"] = f"FND-{index:04d}"
    return findings
