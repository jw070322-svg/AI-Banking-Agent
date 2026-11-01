"""analysis.evaluate —— 用标准答案评估异常识别效果。

环境生成 Agent 会在场景里附带 `expected_insights`（带证据交易 ID），
本模块把 `detect_anomalies()` 的结果和它做匹配，计算准确率相关指标：

- TP：标准答案有，识别到了；
- FP：识别到了，但标准答案没有；
- FN：标准答案有，但没识别到；
- precision = TP / (TP + FP)，recall = TP / (TP + FN)。

匹配规则按类型不同：
- 有证据交易 ID 的类型（工资、重复扣款、异常消费、转账失败）：证据有交集即算匹配；
- 还款：同一张卡；
- 订阅：同一商户；
- 生日：同一亲属关系；
- 预算锁定：只可能有一条，直接匹配。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set, Tuple

from .anomaly import detect_anomalies


def _evidence(item: Dict[str, Any]) -> Set[str]:
    return {value for value in item.get("evidence_transaction_ids", []) if value}


def _details(item: Dict[str, Any]) -> Dict[str, Any]:
    value = item.get("details")
    return value if isinstance(value, dict) else {}


def _matches(expected: Dict[str, Any], detected: Dict[str, Any]) -> bool:
    if expected.get("insight_type") != detected.get("insight_type"):
        return False

    expected_evidence = _evidence(expected)
    detected_evidence = _evidence(detected)
    if expected_evidence and detected_evidence:
        return bool(expected_evidence & detected_evidence)

    insight_type = expected.get("insight_type")
    if insight_type == "upcoming_bill":
        return expected.get("related_card_id") == detected.get("related_card_id")
    if insight_type == "subscription_renewal":
        return _details(expected).get("merchant") == _details(detected).get("merchant")
    if insight_type == "birthday_upcoming":
        return _details(expected).get("relation") == _details(detected).get("relation")
    if insight_type == "budget_lock":
        return True
    return False


def _metrics(tp: int, fp: int, fn: int) -> Dict[str, Any]:
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def evaluate_detection(data: Dict[str, Any]) -> Dict[str, Any]:
    """对比标准答案与识别结果，返回整体和分类型指标。"""
    expected_items = [
        item for item in data.get("expected_insights", []) or []
        if isinstance(item, dict)
    ]
    detected_items = detect_anomalies(data)

    matched_detected: Set[int] = set()
    missed: List[Dict[str, Any]] = []
    matched: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

    for expected in expected_items:
        for index, detected in enumerate(detected_items):
            if index in matched_detected:
                continue
            if _matches(expected, detected):
                matched_detected.add(index)
                matched.append((expected, detected))
                break
        else:
            missed.append(expected)

    false_positives = [
        detected for index, detected in enumerate(detected_items)
        if index not in matched_detected
    ]

    types = sorted({item.get("insight_type") for item in expected_items + detected_items})
    by_type: Dict[str, Dict[str, Any]] = {}
    for insight_type in types:
        expected_count = sum(1 for item in expected_items if item.get("insight_type") == insight_type)
        detected_count = sum(1 for item in detected_items if item.get("insight_type") == insight_type)
        tp = sum(
            1 for expected, detected in matched
            if expected.get("insight_type") == insight_type
        )
        fn = expected_count - tp
        fp = detected_count - tp
        row = _metrics(tp, fp, fn)
        row.update({"expected": expected_count, "detected": detected_count})
        by_type[insight_type] = row

    tp_total = len(matched)
    fp_total = len(false_positives)
    fn_total = len(missed)
    summary = _metrics(tp_total, fp_total, fn_total)
    summary.update({
        "expected": len(expected_items),
        "detected": len(detected_items),
    })

    return {
        "summary": summary,
        "by_type": by_type,
        "missed": [
            {
                "insight_type": item.get("insight_type"),
                "title": item.get("title"),
                "date": item.get("date"),
                "evidence_transaction_ids": item.get("evidence_transaction_ids", []),
            }
            for item in missed
        ],
        "false_positives": [
            {
                "insight_type": item.get("insight_type"),
                "title": item.get("title"),
                "date": item.get("date"),
                "evidence_transaction_ids": item.get("evidence_transaction_ids", []),
            }
            for item in false_positives
        ],
    }


def aggregate_evaluations(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """把多份场景的评估结果合并成一份总指标。"""
    totals: Dict[str, Dict[str, int]] = {}
    overall = {"tp": 0, "fp": 0, "fn": 0, "expected": 0, "detected": 0}

    for result in results:
        summary = result["summary"]
        for key in ("tp", "fp", "fn", "expected", "detected"):
            overall[key] += int(summary.get(key, 0))
        for insight_type, row in result.get("by_type", {}).items():
            bucket = totals.setdefault(
                insight_type, {"tp": 0, "fp": 0, "fn": 0, "expected": 0, "detected": 0}
            )
            for key in ("tp", "fp", "fn", "expected", "detected"):
                bucket[key] += int(row.get(key, 0))

    by_type: Dict[str, Dict[str, Any]] = {}
    for insight_type, bucket in sorted(totals.items()):
        row = _metrics(bucket["tp"], bucket["fp"], bucket["fn"])
        row.update({"expected": bucket["expected"], "detected": bucket["detected"]})
        by_type[insight_type] = row

    summary = _metrics(overall["tp"], overall["fp"], overall["fn"])
    summary.update({"expected": overall["expected"], "detected": overall["detected"]})
    return {"summary": summary, "by_type": by_type}
