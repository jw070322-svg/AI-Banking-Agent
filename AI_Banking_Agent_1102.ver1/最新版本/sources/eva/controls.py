"""合规控制矩阵：义务 → 控制 → 证据 → 审核状态。

每个 Action Log 的 `risk_check` 会带一组 `controls`，其中每项包含
control_id、obligation、control、owner、review_status、evidence_ttl_days
和 evidence_hash。审核人可以用 evidence_hash 定位对应日志字段，检查证据
是否被篡改；`review_status` 明确区分已实现、Demo 级和待上游确认。

注意：这不能替代正式合规评审。它只是把“做了什么控制、证据在哪里、
谁负责、审核到哪一步”变成可机器读取的记录。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ComplianceControl:
    control_id: str
    obligation: str
    control: str
    owner: str
    review_status: str  # implemented / implemented_demo / pending_upstream
    evidence_fields: tuple[str, ...]
    evidence_ttl_days: int


CONTROLS: tuple[ComplianceControl, ...] = (
    ComplianceControl(
        control_id="RC-01",
        obligation="资金变动前必须完成确定性策略检查",
        control="PolicyEngine.check + fail closed",
        owner="risk-module",
        review_status="implemented",
        evidence_fields=(
            "policy_version",
            "policy_config_hash",
            "policy_check_id",
            "checks",
            "risk_flags",
        ),
        evidence_ttl_days=1,
    ),
    ComplianceControl(
        control_id="RC-02",
        obligation="高风险操作必须使用服务端预览并防止参数篡改",
        control="PreviewStore + preview_hash + expires_at",
        owner="risk-module",
        review_status="implemented",
        evidence_fields=(
            "preview_id",
            "preview_hash",
            "expires_at",
            "binding",
        ),
        evidence_ttl_days=1,
    ),
    ComplianceControl(
        control_id="RC-03",
        obligation="资金变动必须获得一次性用户确认",
        control="Approval + confirmation_id + used_at",
        owner="risk-module",
        review_status="implemented",
        evidence_fields=(
            "approval_id",
            "confirmation_id",
            "decision",
            "one_time",
            "used_at",
        ),
        evidence_ttl_days=1,
    ),
    ComplianceControl(
        control_id="RC-04",
        obligation="R4 操作必须通过 step-up 认证",
        control="StepUpAuthenticator 强制断言校验与一次性消费",
        owner="risk-module",
        review_status="implemented_demo",
        evidence_fields=(
            "auth_method",
            "step_up_verified",
            "step_up_simulated",
        ),
        evidence_ttl_days=1,
    ),
    ComplianceControl(
        control_id="RC-05",
        obligation="提示注入与不可信内容不得改变授权或工具参数",
        control="ComplianceScanner + 固定模板 + 内容隔离标记",
        owner="risk-module",
        review_status="implemented",
        evidence_fields=(
            "findings",
            "blocked",
            "untrusted_content_findings",
        ),
        evidence_ttl_days=1,
    ),
    ComplianceControl(
        control_id="RC-06",
        obligation="日志与审计记录必须最小化 PII",
        control="ComplianceScanner.redact + ActionLogWriter 写前二次扫描",
        owner="risk-module",
        review_status="implemented",
        evidence_fields=(
            "redaction_applied",
            "pii_scan",
        ),
        evidence_ttl_days=1,
    ),
    ComplianceControl(
        control_id="RC-07",
        obligation="关键 Agent Action 必须可追溯",
        control="8 字段 .md Action Log + 应急 JSONL 通道",
        owner="risk-module",
        review_status="implemented",
        evidence_fields=(
            "log_format",
            "timestamp",
            "audit_id",
            "fallback_path",
        ),
        evidence_ttl_days=30,
    ),
    ComplianceControl(
        control_id="RC-08",
        obligation="需要人工复核的异常必须被标记",
        control="requires_manual_review + audit 告警",
        owner="risk-module",
        review_status="implemented",
        evidence_fields=(
            "requires_manual_review",
            "severity",
        ),
        evidence_ttl_days=30,
    ),
)

CONTROLS_BY_ID = {control.control_id: control for control in CONTROLS}


def _hash(payload: Any) -> str:
    text = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str
    )
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_control_records(
    evidence_by_control: dict[str, Any]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for control in CONTROLS:
        if control.control_id not in evidence_by_control:
            continue
        evidence = evidence_by_control[control.control_id]
        records.append(
            {
                "control_id": control.control_id,
                "obligation": control.obligation,
                "control": control.control,
                "owner": control.owner,
                "review_status": control.review_status,
                "evidence_ttl_days": control.evidence_ttl_days,
                "evidence_fields": list(control.evidence_fields),
                "evidence_hash": _hash(evidence),
            }
        )
    return records


def missing_evidence(
    evidence_by_control: dict[str, Any]
) -> list[str]:
    return [
        control.control_id
        for control in CONTROLS
        if control.control_id not in evidence_by_control
    ]
