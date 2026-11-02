"""perturbations.py —— 扰动/对抗样例，用来量化误报。

环境生成 Agent 的 A~G 样例和识别器同源，100% 指标只能说明口径一致。
真正要回答的问题是：

- 同一家店、同一金额，但相隔半天买两次，会不会被误判成重复扣款？
- 房租、学费这种固定大额支出，会不会被误判成异常消费？
- 订阅只涨了 10 块钱，算不算调价？
- 退款冲正的一对流水，会不会被当成重复扣款？

本文件用一组手工构造的最小场景，对每个问题给出"应该报 / 不应该报"的
标准答案，然后统计识别器的 TP / FP / FN。

用法：
    python cli.py perturb
    python perturbations.py
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from analysis import detect_anomalies


def _transaction(
    transaction_id: str,
    when: str,
    amount_minor: int,
    merchant: str,
    *,
    category: str = "购物",
    time: Optional[str] = None,
    transaction_type: str = "expense",
    status: str = "booked",
    **extra: Any,
) -> Dict[str, Any]:
    transaction = {
        "transaction_id": transaction_id,
        "account_id": "ACC-P",
        "date": when,
        "amount_minor": amount_minor,
        "amount": -amount_minor if transaction_type == "expense" else amount_minor,
        "direction": "debit" if transaction_type == "expense" else "credit",
        "transaction_type": transaction_type,
        "category": category,
        "merchant": merchant,
        "status": status,
    }
    if time:
        transaction["time"] = time
    transaction.update(extra)
    return transaction


def _scenario(transactions: List[Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    scenario = {
        "scenario_id": "PERT",
        "scenario_type": "PERT",
        "created_at": "2026-10-23T00:00:00",
        "currency": "CNY",
        "accounts": [{"account_id": "ACC-P", "balance_minor": 1_000_000}],
        "transactions": transactions,
    }
    scenario.update(extra)
    return scenario


def _bill(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "card_id": "CARD-P",
        "due_date": "2026-11-10",
        "statement_date": "2026-10-09",
        "status": "unpaid",
        "total_amount_minor": sum(item["amount_minor"] for item in items),
        "paid_amount_minor": 0,
        "outstanding_amount_minor": sum(item["amount_minor"] for item in items),
        "items": items,
    }


def _credit_item(item_id: str, when: str, amount_minor: int, merchant: str) -> Dict[str, Any]:
    return {
        "transaction_id": item_id,
        "card_id": "CARD-P",
        "date": when,
        "amount_minor": amount_minor,
        "amount": -amount_minor,
        "direction": "debit",
        "transaction_type": "expense",
        "category": "购物",
        "merchant": merchant,
        "status": "booked",
    }


def _case(
    name: str,
    target_type: str,
    should_detect: bool,
    scenario: Dict[str, Any],
    *,
    evidence: Optional[Set[str]] = None,
    severity: Optional[str] = None,
    note: str = "",
) -> Dict[str, Any]:
    return {
        "name": name,
        "target_type": target_type,
        "should_detect": should_detect,
        "expected_evidence": evidence or set(),
        "expected_severity": severity,
        "scenario": scenario,
        "note": note,
    }


def _small_expenses(prefix: str, months: List[str], per_month: int = 4) -> List[Dict[str, Any]]:
    """每月若干笔不同商户的小额消费，用于把平均支出拉低。"""
    transactions: List[Dict[str, Any]] = []
    for month in months:
        for index in range(per_month):
            transactions.append(_transaction(
                f"{prefix}-{month}-{index}",
                f"{month}-1{index % 9}",
                10_000 + index * 100,
                f"小商户{index}",
                category="餐饮",
            ))
    return transactions


def build_cases() -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []

    # ---------------- 重复扣款：真重复 ----------------
    cases.append(_case(
        "重复扣款_2分钟内两笔同额",
        "duplicate_charge", True,
        _scenario([
            _transaction("P1", "2026-10-18", 30_000, "某电商平台", time="10:00:00"),
            _transaction("P2", "2026-10-18", 30_000, "某电商平台", time="10:02:00"),
        ]),
        evidence={"P1", "P2"}, severity="high",
        note="同商户、同金额、2 分钟内，典型重复扣款",
    ))
    cases.append(_case(
        "重复扣款_3笔都在窗口内",
        "duplicate_charge", True,
        _scenario([
            _transaction("P1", "2026-10-18", 30_000, "某电商平台", time="10:00:00"),
            _transaction("P2", "2026-10-18", 30_000, "某电商平台", time="10:03:00"),
            _transaction("P3", "2026-10-18", 30_000, "某电商平台", time="10:07:00"),
        ]),
        evidence={"P1", "P2", "P3"}, severity="high",
        note="三笔连续重复，应全部作为证据",
    ))
    cases.append(_case(
        "重复扣款_没有时间信息",
        "duplicate_charge", True,
        _scenario([
            _transaction("P1", "2026-10-18", 30_000, "某电商平台"),
            _transaction("P2", "2026-10-18", 30_000, "某电商平台"),
        ]),
        evidence={"P1", "P2"}, severity="medium",
        note="缺少时间，只能保守提示 medium",
    ))
    cases.append(_case(
        "重复扣款_信用卡两笔同额",
        "duplicate_charge", True,
        _scenario(
            [_transaction("S1", "2026-10-01", 500_000, "示例科技", category="工资",
                          transaction_type="income")],
            credit_card_bill=_bill([
                _credit_item("CT1", "2026-10-12", 45_000, "某商场"),
                _credit_item("CT2", "2026-10-12", 45_000, "某商场"),
            ]),
        ),
        evidence={"CT1", "CT2"}, severity="medium",
        note="信用卡账单里同商户同额同日两笔",
    ))

    # ---------------- 重复扣款：容易误报的正常消费 ----------------
    cases.append(_case(
        "正常消费_同店同额相隔半天",
        "duplicate_charge", False,
        _scenario([
            _transaction("P1", "2026-10-18", 3_000, "某咖啡店", time="09:00:00"),
            _transaction("P2", "2026-10-18", 3_000, "某咖啡店", time="18:00:00"),
        ]),
        note="上午、下午各一杯同样的咖啡，属正常消费",
    ))
    cases.append(_case(
        "正常消费_同店同额但日期不同",
        "duplicate_charge", False,
        _scenario([
            _transaction("P1", "2026-10-17", 30_000, "某电商平台", time="10:00:00"),
            _transaction("P2", "2026-10-18", 30_000, "某电商平台", time="10:00:00"),
        ]),
        note="连续两天下单同样商品，不应判重复",
    ))
    cases.append(_case(
        "正常消费_同店同日金额差1分",
        "duplicate_charge", False,
        _scenario([
            _transaction("P1", "2026-10-18", 30_000, "某电商平台", time="10:00:00"),
            _transaction("P2", "2026-10-18", 30_001, "某电商平台", time="10:01:00"),
        ]),
        note="金额不同，属于两笔不同订单",
    ))
    cases.append(_case(
        "正常消费_同额同日不同商户",
        "duplicate_charge", False,
        _scenario([
            _transaction("P1", "2026-10-18", 30_000, "某电商平台", time="10:00:00"),
            _transaction("P2", "2026-10-18", 30_000, "另一家电商", time="10:01:00"),
        ]),
        note="两家不同商户各买一次",
    ))
    cases.append(_case(
        "正常消费_支出与退款配对",
        "duplicate_charge", False,
        _scenario([
            _transaction("P1", "2026-10-18", 30_000, "某电商平台", time="10:00:00"),
            _transaction("R1", "2026-10-18", 30_000, "某电商平台", time="10:05:00",
                         transaction_type="refund", category="购物"),
        ]),
        note="退款冲正不是重复扣款",
    ))
    cases.append(_case(
        "正常消费_一笔已完成一笔被拒",
        "duplicate_charge", False,
        _scenario([
            _transaction("P1", "2026-10-18", 30_000, "某电商平台", time="10:00:00"),
            _transaction("P2", "2026-10-18", 30_000, "某电商平台", time="10:01:00",
                         status="rejected"),
        ]),
        note="被拒绝的交易不入账，不构成重复",
    ))
    cases.append(_case(
        "正常消费_连锁店同额但不同日期时间",
        "duplicate_charge", False,
        _scenario([
            _transaction("P1", "2026-10-10", 8_000, "某便利店", time="08:00:00"),
            _transaction("P2", "2026-10-11", 8_000, "某便利店", time="08:00:00"),
            _transaction("P3", "2026-10-12", 8_000, "某便利店", time="08:00:00"),
        ]),
        note="每天早上一杯固定价格的咖啡/早餐",
    ))

    # ---------------- 异常大额消费 ----------------
    cases.append(_case(
        "异常消费_单笔远超平均",
        "unusual_spending", True,
        _scenario(_small_expenses("U1", ["2026-10"], per_month=10) + [
            _transaction("BIG1", "2026-10-18", 800_000, "某奢侈品店"),
        ]),
        evidence={"BIG1"}, severity="medium",
        note="10 笔百元支出 + 1 笔 8000 元奢侈品",
    ))
    cases.append(_case(
        "异常消费_大额但符合平均",
        "unusual_spending", False,
        _scenario(
            _small_expenses("U2", ["2026-08", "2026-09", "2026-10"], per_month=10)
            + [
                _transaction("RENT1", "2026-08-01", 500_000, "某房东", category="居住"),
                _transaction("RENT2", "2026-09-01", 500_000, "某房东", category="居住"),
                _transaction("RENT3", "2026-10-01", 500_000, "某房东", category="居住"),
            ]
        ),
        note="每月固定 5000 元房租，不应报异常",
    ))
    cases.append(_case(
        "异常消费_固定大额但金额小幅波动",
        "unusual_spending", False,
        _scenario(
            _small_expenses("U3", ["2026-08", "2026-09", "2026-10"], per_month=10)
            + [
                _transaction("UTIL1", "2026-08-05", 180_000, "某物业", category="居住"),
                _transaction("UTIL2", "2026-09-05", 190_000, "某物业", category="居住"),
                _transaction("UTIL3", "2026-10-05", 195_000, "某物业", category="居住"),
            ]
        ),
        note="每月物业费在 ±10% 内波动，属于固定义务",
    ))
    cases.append(_case(
        "异常消费_未达到1000元门槛",
        "unusual_spending", False,
        _scenario(_small_expenses("U4", ["2026-10"], per_month=2) + [
            _transaction("B1", "2026-10-09", 90_000, "某餐厅"),
        ]),
        note="900 元虽然高于平均，但低于最低关注金额",
    ))
    cases.append(_case(
        "异常消费_样本不足3笔",
        "unusual_spending", False,
        _scenario([
            _transaction("B1", "2026-10-09", 500_000, "某商场"),
            _transaction("B2", "2026-10-10", 10_000, "某餐厅"),
        ]),
        note="只有两笔支出，不做异常判断",
    ))
    cases.append(_case(
        "异常消费_大额一次性支出",
        "unusual_spending", True,
        _scenario(_small_expenses("U5", ["2026-10"], per_month=10) + [
            _transaction("BIG2", "2026-10-20", 800_000, "某商场"),
        ]),
        evidence={"BIG2"}, severity="medium",
        note="10 笔小额 + 1 笔 8000 元一次性消费",
    ))
    cases.append(_case(
        "正常消费_5000元家电",
        "unusual_spending", False,
        _scenario(_small_expenses("U6", ["2026-10"], per_month=10) + [
            _transaction("LAPTOP", "2026-10-20", 500_000, "某电脑商城", category="家居"),
        ]),
        note="买一台 5000 元电脑，家居类别门槛是 20000 元",
    ))
    cases.append(_case(
        "正常消费_装修20000元",
        "unusual_spending", False,
        _scenario(_small_expenses("U7", ["2026-10"], per_month=10) + [
            _transaction("DECOR", "2026-10-20", 2_000_000, "某装修公司", category="装修"),
        ]),
        note="一次性装修支出，装修类别门槛是 30000 元",
    ))
    cases.append(_case(
        "正常消费_旅行8000元",
        "unusual_spending", False,
        _scenario(_small_expenses("U8", ["2026-10"], per_month=10) + [
            _transaction("TRIP", "2026-10-20", 800_000, "某旅行平台", category="旅行"),
        ]),
        note="一次旅行 8000 元，旅行类别门槛是 20000 元",
    ))
    cases.append(_case(
        "正常消费_医疗30000元",
        "unusual_spending", False,
        _scenario(_small_expenses("U9", ["2026-10"], per_month=10) + [
            _transaction("MED1", "2026-10-20", 3_000_000, "某医院", category="医疗"),
        ]),
        note="医疗 30000 元，医疗类别门槛是 50000 元",
    ))
    cases.append(_case(
        "异常消费_极端医疗支出",
        "unusual_spending", True,
        _scenario(_small_expenses("U10", ["2026-10"], per_month=10) + [
            _transaction("MED2", "2026-10-20", 8_000_000, "某医院", category="医疗"),
        ]),
        evidence={"MED2"}, severity="medium",
        note="医疗 80000 元，超过类别门槛且远高于平均，仍应提示",
    ))

    # ---------------- 订阅调价 ----------------
    cases.append(_case(
        "订阅调价_涨价",
        "subscription_price_change", True,
        _scenario([
            _transaction("S1", "2026-08-01", 1_990, "某视频平台", category="订阅"),
            _transaction("S2", "2026-09-01", 1_990, "某视频平台", category="订阅"),
            _transaction("S3", "2026-10-01", 2_590, "某视频平台", category="订阅"),
        ]),
        evidence={"S2", "S3"}, severity="high",
        note="19.9 元涨到 25.9 元",
    ))
    cases.append(_case(
        "订阅调价_降价",
        "subscription_price_change", True,
        _scenario([
            _transaction("S1", "2026-08-01", 2_590, "某视频平台", category="订阅"),
            _transaction("S2", "2026-09-01", 2_590, "某视频平台", category="订阅"),
            _transaction("S3", "2026-10-01", 1_990, "某视频平台", category="订阅"),
        ]),
        evidence={"S2", "S3"}, severity="medium",
        note="25.9 元降到 19.9 元",
    ))
    cases.append(_case(
        "订阅调价_金额不变",
        "subscription_price_change", False,
        _scenario([
            _transaction("S1", "2026-08-01", 1_990, "某视频平台", category="订阅"),
            _transaction("S2", "2026-09-01", 1_990, "某视频平台", category="订阅"),
            _transaction("S3", "2026-10-01", 1_990, "某视频平台", category="订阅"),
        ]),
        note="正常续费，不应报调价",
    ))
    cases.append(_case(
        "订阅调价_只有1元波动",
        "subscription_price_change", False,
        _scenario([
            _transaction("S1", "2026-09-01", 1_990, "某视频平台", category="订阅"),
            _transaction("S2", "2026-10-01", 2_000, "某视频平台", category="订阅"),
        ]),
        note="1 元以内的波动是汇率/税费尾差，不提示",
    ))

    return cases


def run_cases(cases: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """运行全部扰动样例，返回逐条结果与汇总指标。"""
    cases = cases if cases is not None else build_cases()
    rows: List[Dict[str, Any]] = []
    tp = fp = fn = 0

    for case in cases:
        findings = detect_anomalies(case["scenario"])
        targets = [
            finding for finding in findings
            if finding["insight_type"] == case["target_type"]
        ]

        matched: Optional[Dict[str, Any]] = None
        if case["should_detect"]:
            for finding in targets:
                evidence = set(finding["evidence_transaction_ids"])
                if not case["expected_evidence"] or case["expected_evidence"] <= evidence:
                    matched = finding
                    break

        if case["should_detect"]:
            if matched is not None:
                tp += 1
            else:
                fn += 1
            case_fp = len(targets) - (1 if matched is not None else 0)
        else:
            case_fp = len(targets)
        fp += case_fp

        severity_ok = True
        if matched is not None and case["expected_severity"]:
            severity_ok = matched["severity"] == case["expected_severity"]

        passed = (
            (matched is not None and severity_ok and case_fp == 0)
            if case["should_detect"]
            else (case_fp == 0)
        )

        rows.append({
            "name": case["name"],
            "target_type": case["target_type"],
            "should_detect": case["should_detect"],
            "detected": len(targets),
            "matched": matched is not None,
            "severity": matched["severity"] if matched else None,
            "severity_ok": severity_ok,
            "passed": passed,
            "note": case["note"],
        })

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "cases": rows,
        "summary": {
            "total": len(cases),
            "passed": sum(1 for row in rows if row["passed"]),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        },
    }


def print_results(result: Dict[str, Any]) -> None:
    print(f"\n===== 扰动样例（{result['summary']['total']} 个）=====")
    for row in result["cases"]:
        status = "PASS" if row["passed"] else "FAIL"
        expected = "应报" if row["should_detect"] else "不应报"
        print(
            f"[{status}] {row['name']:<32} {expected}  实际 {row['detected']} 条"
            f"  {row['note']}"
        )
    summary = result["summary"]
    print(
        f"\n通过 {summary['passed']}/{summary['total']}  "
        f"TP {summary['tp']}  FP {summary['fp']}  FN {summary['fn']}  "
        f"P {summary['precision']:.2%}  R {summary['recall']:.2%}  F1 {summary['f1']:.2%}"
    )


if __name__ == "__main__":
    print_results(run_cases())
