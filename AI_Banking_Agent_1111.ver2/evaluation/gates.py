"""评测门禁代码（DESIGN §6/§7 + 工作包A §4.2 + 工作包C缺口修复）。

- check_gates(findings)：旧诊断接口，保留用于诊断，不得直接签发发布许可。
- evaluate_release_gate(report, policy)：三态发布门禁（pass/fail/incomplete），
  发布决定由本函数负责。
区分：正常排除超预算候选（budget_normal_exclusion，正确业务行为，不计错误）
与错误推荐超预算组合（budget_override_recommendation，发布失败）。
策略必含 evidence_freshness_days（证据时效）与 allowed_sources（数据来源白名单），
两者均强制执行。"""
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from schema_check import SchemaValidationError, load_schema, validate  # noqa: E402
from training_pipeline import PII_PATTERNS  # noqa: E402

BUDGET_OVERRIDE = "budget_override"
PRIVACY_LEAK = "privacy_leak"
BUDGET_OVERRIDE_RECOMMENDATION = "budget_override_recommendation"
BUDGET_NORMAL_EXCLUSION = "budget_normal_exclusion"

_REQUIRED_REPORT_FIELDS = ["schema_version", "run_id", "evaluated_at", "model_hash",
                           "template_hash", "dataset_hash", "evaluator_version",
                           "required_checks", "completed_checks", "sample_counts",
                           "findings", "metrics"]
def privacy_leak_findings(sent_text, raw_event=None):
    """外发文本检查：事件原文回显或 PII 出现即记隐私外发发现。"""
    findings = []
    sent = sent_text or ""
    if raw_event and raw_event.strip() and raw_event in sent:
        findings.append({"type": PRIVACY_LEAK, "detail": "事件原文出现在外发文本"})
    for kind, pattern in PII_PATTERNS.items():
        if pattern.search(sent):
            findings.append({"type": PRIVACY_LEAK, "detail": f"外发文本含PII：{kind}"})
    return findings


def budget_override_findings(worst_case_cents, budget_max_cents):
    """组合最坏区间超出预算上限即记预算覆盖错误（DESIGN §6：预算覆盖错误须为0）。"""
    if worst_case_cents is None or budget_max_cents is None:
        return []
    if worst_case_cents > budget_max_cents:
        return [{"type": BUDGET_OVERRIDE,
                 "detail": f"最坏组合 {worst_case_cents} 分超出预算上限 {budget_max_cents} 分"}]
    return []


def check_gates(findings):
    """旧诊断接口（§4.2）：只作诊断，不能直接签发发布许可。"""
    budget = [f for f in findings if f.get("type") == BUDGET_OVERRIDE]
    privacy = [f for f in findings if f.get("type") == PRIVACY_LEAK]
    return {"pass": not budget and not privacy,
            "budget_override_count": len(budget),
            "privacy_leak_count": len(privacy),
            "details": findings}


def _meets_threshold(value, threshold):
    if not isinstance(threshold, dict):
        return value == threshold
    if "min" in threshold and (value is None or value < threshold["min"]):
        return False
    if "max" in threshold and (value is None or value > threshold["max"]):
        return False
    return True


def _age_days_from(verified_at, evaluated_at):
    """证据时间距评测时间的天数；解析失败返回 None。"""
    try:
        verified = datetime.fromisoformat(str(verified_at)[:10]).date()
        evaluated = datetime.fromisoformat(str(evaluated_at)[:10]).date()
        return (evaluated - verified).days
    except (ValueError, TypeError):
        return None


def _incomplete(reasons, counts, coverage, artifact_hashes, extra=None):
    return {"decision": "incomplete", "reasons": reasons + (extra or []),
            "counts": counts, "coverage": coverage, "artifact_hashes": artifact_hashes}


def evaluate_release_gate(report, policy):
    """三态发布门禁（§4.2 + S1.3 修复 R3 fail-open）。

    - 策略与报告先过各自契约（release_policy/release_report Schema），非法即 incomplete
    - 每个适用检查**必须**携带非空 sources（⊆ allowed）与有效 evidence_verified_at
      （格式合法、非未来、在 evidence_freshness_days 内）——缺省即 incomplete，不再跳过
    - sample_counts 必须与唯一样本数一致（重复样本不充数）
    - report.required_checks 必须与 policy.required_checks 一致（不信任自报）
    - 指标拒绝非有限值与缺失；金额拒绝缺失/非有限
    - 硬失败（错误推荐超预算/隐私外发）优先于 incomplete：即使报告其他字段不完整也 fail
    - 不适用检查须有明确理由且策略允许，不当作已通过样本
    - 全部必检完成且指标达标 → pass
    """
    reasons, coverage, artifact_hashes = [], {}, {}
    counts = {"passed_checks": 0, "incomplete_checks": 0, "not_applicable_checks": 0,
              "budget_override_recommendation": 0, "privacy_leak": 0,
              "budget_normal_exclusion": 0}

    # 1) 策略契约（S1.3：策略本身过 Schema，未配置/缺字段不能发布）
    try:
        validate(policy, load_schema("release_policy.schema.json"), path="policy")
    except SchemaValidationError as exc:
        return _incomplete([f"策略不符合契约（未配置完整，禁止发布）：{exc}"],
                           counts, coverage, artifact_hashes)
    # 2) 报告契约
    try:
        validate(report, load_schema("release_report.schema.json"), path="report")
    except SchemaValidationError as exc:
        artifact_hashes = {k: report.get(k) for k in
                           ("model_hash", "template_hash", "dataset_hash") if k in report}
        return _incomplete([f"报告不符合契约：{exc}"],
                           counts, coverage, artifact_hashes)
    artifact_hashes = {"model_hash": report["model_hash"],
                       "template_hash": report["template_hash"],
                       "dataset_hash": report["dataset_hash"]}
    if policy.get("expected_model_hash") and \
            report["model_hash"] != policy["expected_model_hash"]:
        return _incomplete([f"model_hash 与策略期望不符：{report['model_hash']}"],
                           counts, coverage, artifact_hashes)
    # 3) 硬失败优先（S1.3 R3：即使报告其他字段不完整也不被 incomplete 掩盖）
    hard_failures = []
    for finding in report["findings"]:
        ftype = finding.get("type")
        if ftype == BUDGET_OVERRIDE_RECOMMENDATION:
            counts["budget_override_recommendation"] += 1
            hard_failures.append(f"检测到错误推荐超预算组合：{finding.get('detail', '')}")
        elif ftype == PRIVACY_LEAK:
            counts["privacy_leak"] += 1
            hard_failures.append(f"检测到隐私外发：{finding.get('detail', '')}")
        elif ftype == BUDGET_NORMAL_EXCLUSION:
            counts["budget_normal_exclusion"] += 1  # 正确业务行为，不计错误
    if hard_failures:
        return {"decision": "fail", "reasons": hard_failures,
                "counts": counts, "coverage": coverage, "artifact_hashes": artifact_hashes}
    # 4) 必检清单对账：报告声明与策略一致（不信任自报）
    required = set(policy["required_checks"])
    if set(report["required_checks"]) != required:
        return _incomplete([f"报告 required_checks 与策略不一致："
                            f"报告 {sorted(set(report['required_checks']))}，"
                            f"策略 {sorted(required)}"],
                           counts, coverage, artifact_hashes)
    completed = {c.get("check"): c for c in report["completed_checks"]}
    # 5) 逐检查核验（证据元数据必填——S1.3 闭合 fail-open）
    for check in sorted(required):
        entry = completed.get(check)
        if entry is None:
            reasons.append(f"必检项未执行：{check}")
            counts["incomplete_checks"] += 1
            continue
        if entry.get("applicable") is False:
            if entry.get("not_applicable_reason") and \
                    check in policy.get("not_applicable_allowed", []):
                counts["not_applicable_checks"] += 1
            else:
                reasons.append(f"不适用检查缺少理由或策略不允许：{check}")
                counts["incomplete_checks"] += 1
            continue
        ids = entry.get("sample_ids") or []
        unique = set(ids)
        if len(ids) != len(unique):
            reasons.append(f"{check} 存在重复样本充数（{len(ids)} 条 → {len(unique)} 唯一）")
        if not unique:
            reasons.append(f"{check} 无样本")
            counts["incomplete_checks"] += 1
            continue
        min_n = policy["min_samples_per_scenario"].get(check, 0)
        if len(unique) < min_n:
            reasons.append(f"{check} 样本不足：{len(unique)}/{min_n}")
            counts["incomplete_checks"] += 1
            continue
        check_failures = []
        if entry.get("budget_applicable"):
            amounts = entry.get("amounts_cents")
            if not amounts or any(not isinstance(a, int) or isinstance(a, bool)
                                  or not math.isfinite(a) or a < 0 for a in amounts):
                check_failures.append(f"{check} 适用预算检查但金额缺失/非有限/口径未知")
        # 数据来源白名单 + **必填**（S1.3：缺省即 incomplete，不再跳过）
        sources = entry.get("sources") or []
        if not sources:
            check_failures.append(f"{check} 缺少数据来源标记（来源白名单强制）")
        else:
            disallowed = sorted(set(sources) - set(policy["allowed_sources"]))
            if disallowed:
                check_failures.append(f"{check} 数据来源不在策略允许范围：{disallowed}")
        # 证据时间必填 + 格式/未来/时效校验（S1.3：缺省即 incomplete，不再跳过）
        verified_at = entry.get("evidence_verified_at")
        if not verified_at:
            check_failures.append(f"{check} 缺少证据核验时间（evidence_verified_at）")
        else:
            age = _age_days_from(verified_at, report["evaluated_at"])
            if age is None:
                check_failures.append(f"{check} 证据时间非法：{verified_at}")
            elif age < 0:
                check_failures.append(f"{check} 证据时间为未来日期：{verified_at}")
            elif age > int(policy["evidence_freshness_days"]):
                check_failures.append(f"{check} 证据过期：{verified_at} 距评测 {age} 天 "
                                      f"> 允许 {policy['evidence_freshness_days']} 天")
        if check_failures:
            reasons.extend(check_failures)
            counts["incomplete_checks"] += 1
            continue
        counts["passed_checks"] += 1
    coverage = {"required": sorted(required),
                "completed": sorted(k for k in completed if k in required),
                "not_applicable": sorted(k for k, c in completed.items()
                                         if c.get("applicable") is False)}
    # 6) 指标阈值（非有限/缺失拒绝）
    for metric, threshold in policy["metric_thresholds"].items():
        value = report["metrics"].get(metric)
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            reasons.append(f"指标缺失或非有限：{metric}")
            counts["incomplete_checks"] += 1
        elif not _meets_threshold(value, threshold):
            reasons.append(f"指标未达标：{metric}={value}（阈值 {threshold}）")
    if reasons:
        return _incomplete(reasons, counts, coverage, artifact_hashes)
    return {"decision": "pass", "reasons": [], "counts": counts,
            "coverage": coverage, "artifact_hashes": artifact_hashes}
