"""Prepared bridges to the completed Risk Engine and Compliance Guard.

These adapters implement Module 6's existing ports without modifying either
completed module. Readiness is reported honestly:

- `ExistingComplianceGuardAdapter` directly calls the completed
  `ComplianceScanner`. It is a real bridge, but `is_verified=False` by default
  because this prototype has not been through a production security review.
  Module 6 therefore keeps `execute_transaction` fail-closed.
- `ExistingRiskEngineAdapter` only authorizes a tool call when a separate
  `RiskAuthorizationRegistry` holds evidence from the completed engine's
  plan/preview/confirm lifecycle. It never collapses R4 approval into a bare
  boolean and never invents risk rules. The evidence registry is in-memory and
  demo-only, so `is_verified=False` by default too.

A production deployment may set `verified=True` only after integration tests,
review and a durable evidence store are in place.

From the 1030 bridge round on, `verified=True` alone is not enough: the adapter
also needs a verification ticket issued by `security/verification.py`. The
ticket records the hashes of the bridge source files it was issued against, so
editing this module invalidates every earlier ticket. This keeps "verified" a
property that must be earned by a passing suite over unchanged code instead of
a boolean anyone can type.

Identity mapping used by the web bridge: the web application's
`state['customer_id']` is Module 8's `Principal.user_id`, and
`state['session_id']` is Module 8's `session_id`.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from ..models import new_id
from ..risk.compliance import ComplianceScanner
from ..tool_calling.adapters import (
    ComplianceEvaluationRequest,
    ComplianceEvaluationResult,
    ComplianceGuardAdapter,
    RiskEngineAdapter,
    RiskEvaluationRequest,
    RiskEvaluationResult,
)
from .compatibility import CompatibleScanner
from .models import SECURITY_POLICY_VERSION
from .sessions import ensure_aware, iso, parse_iso

# Source files whose bytes a verification ticket must have been issued against.
# Editing either file voids every ticket issued before the edit.
VERIFICATION_SOURCES = (
    "first_agent/vendor/eva/security/adapters.py",
    "first_agent/vendor/eva/security/compatibility.py",
)


def ticket_covers(ticket: Any, *relpaths: str) -> bool:
    """Duck-typed check so this module never imports the verification suite."""
    covers = getattr(ticket, "covers", None)
    if ticket is None or not callable(covers):
        return False
    try:
        return bool(covers(*relpaths))
    except Exception:
        return False


def _arguments_hash(
    *,
    user_id: str,
    session_id: str,
    tool_name: str,
    tool_version: str,
    arguments: Mapping[str, Any],
) -> str:
    payload = {
        "user_id": user_id,
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_version": tool_version,
        "arguments": arguments,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# Compliance Guard bridge
# ----------------------------------------------------------------------


class ExistingComplianceGuardAdapter(ComplianceGuardAdapter):
    """Bridge to the completed `bank_agent.risk.compliance.ComplianceScanner`."""

    adapter_name = "Existing ComplianceScanner bridge"
    adapter_kind = "production"
    is_connected = True
    is_verified = False
    description = (
        "Calls the completed ComplianceScanner. Prepared but not verified for "
        "production; Module 6 keeps protected operations fail-closed."
    )

    def __init__(
        self,
        scanner: ComplianceScanner | None = None,
        *,
        verified: bool = False,
        ticket: Any | None = None,
    ) -> None:
        # 1030 修复：默认扫描器必须是 CompatibleScanner。裸 ComplianceScanner
        # 没有 scan_untrusted_content，默认构造会让 evaluate() 直接 AttributeError。
        self.scanner = scanner or CompatibleScanner()
        self.ticket = ticket
        self.is_verified = bool(verified and ticket_covers(ticket, *VERIFICATION_SOURCES))

    def evaluate(
        self, request: ComplianceEvaluationRequest
    ) -> ComplianceEvaluationResult:
        request_report = self.scanner.scan_input(request.request_text or "")
        arguments_text = json.dumps(
            request.arguments, ensure_ascii=False, sort_keys=True, default=str
        )
        # 能力探测而非假设：任何注入的扫描器都能工作，且永远全量扫描
        # （不传 ignore_code_blocks=True，避免静默减弱旧安全规则）。
        scan_untrusted = getattr(self.scanner, "scan_untrusted_content", None)
        argument_report = (
            scan_untrusted("tool_arguments", arguments_text)
            if callable(scan_untrusted)
            else self.scanner.scan_input(arguments_text)
        )
        findings: list[dict[str, Any]] = []
        for item in list(request_report.findings) + list(
            argument_report.findings
        ):
            # Never copy `matched` (it can echo malicious text or secrets).
            findings.append(
                {
                    "code": item.code,
                    "severity": item.severity,
                    "detail": item.detail,
                }
            )
        allowed = (
            request_report.passed
            and argument_report.passed
            and not argument_report.injection_suspected
        )
        reasons = sorted({str(item["code"]) for item in findings})
        return ComplianceEvaluationResult(
            allowed=allowed,
            decision_id=new_id("CDEC"),
            findings=tuple(findings),
            reasons=(
                tuple(reasons)
                if reasons
                else ("COMPLIANCE_SCAN_PASSED",)
            ),
            policy_version=SECURITY_POLICY_VERSION,
            metadata={
                "bridge": "bank_agent.risk.ComplianceScanner",
                "bridge_verified": self.is_verified,
                "source": "existing_completed_module",
            },
        )


# ----------------------------------------------------------------------
# Risk Engine bridge
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class RiskAuthorizationEvidence:
    """Evidence that the completed Risk Engine approved this exact call.

    It is issued only by `RiskAuthorizationRegistry.record_from_risk_engine`,
    which requires a matching preview hash and approval ID. The adapter refuses
    without it.
    """

    authorization_id: str
    user_id: str
    session_id: str
    tool_name: str
    tool_version: str
    arguments_hash: str
    risk_level: str
    preview_hash: str
    approval_id: str
    issued_at: str
    expires_at: str
    policy_version: str = SECURITY_POLICY_VERSION
    consumed_at: str | None = None
    revoked_at: str | None = None
    revoked_reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def is_expired(self, now: datetime) -> bool:
        return now >= parse_iso(self.expires_at)

    def is_usable(self, now: datetime) -> bool:
        return self.consumed_at is None and self.revoked_at is None and not self.is_expired(now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "risk_level": self.risk_level,
            "preview_hash": self.preview_hash,
            "approval_id": self.approval_id,
            "expires_at": self.expires_at,
            "consumed": self.consumed_at is not None,
            "revoked": self.revoked_at is not None,
            "policy_version": self.policy_version,
        }


class RiskAuthorizationRegistry:
    """In-memory evidence store for the bridge. Demo-only, not durable."""

    def __init__(
        self, *, clock=None, expected_policy_version: str = SECURITY_POLICY_VERSION
    ) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        # 证据绑定的策略版本必须仍是当前版本，否则视为已失效（策略变更即撤权）。
        self.expected_policy_version = expected_policy_version
        self._items: dict[str, RiskAuthorizationEvidence] = {}
        self._lock = threading.RLock()

    def record(
        self,
        *,
        user_id: str,
        session_id: str,
        tool_name: str,
        tool_version: str,
        arguments: Mapping[str, Any],
        risk_level: str,
        preview_hash: str,
        approval_id: str,
        ttl_seconds: int = 120,
        metadata: Mapping[str, Any] | None = None,
        policy_version: str | None = None,
    ) -> RiskAuthorizationEvidence:
        if not preview_hash or not approval_id:
            raise ValueError(
                "risk evidence requires a preview hash and approval ID"
            )
        if risk_level not in {"R0", "R1", "R2", "R3", "R4"}:
            raise ValueError("invalid risk level")
        now = ensure_aware(self.clock())
        evidence = RiskAuthorizationEvidence(
            authorization_id=new_id("RAUTH"),
            user_id=user_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_version=tool_version,
            arguments_hash=_arguments_hash(
                user_id=user_id,
                session_id=session_id,
                tool_name=tool_name,
                tool_version=tool_version,
                arguments=arguments,
            ),
            risk_level=risk_level,
            preview_hash=preview_hash,
            approval_id=approval_id,
            issued_at=iso(now),
            expires_at=iso(now + timedelta(seconds=ttl_seconds)),
            policy_version=policy_version or self.expected_policy_version,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._items[evidence.authorization_id] = evidence
        return evidence

    def record_from_risk_engine(
        self,
        *,
        session: Any,
        decision: Any,
        approval: Any,
        tool_name: str,
        tool_version: str,
        arguments: Mapping[str, Any],
        ttl_seconds: int = 120,
    ) -> RiskAuthorizationEvidence:
        """Record evidence produced by the completed Risk Engine.

        This does not compute risk. It only accepts an already-approved
        assessment/approval pair and verifies that the preview hashes match.
        """
        preview = getattr(decision, "preview", None)
        preview_hash = getattr(preview, "preview_hash", None)
        approval_hash = getattr(approval, "preview_hash", None)
        if not preview_hash or preview_hash != approval_hash:
            raise ValueError(
                "approval is not bound to the assessment preview"
            )
        if getattr(approval, "user_id", None) != session.customer_id:
            raise ValueError("approval is not bound to this user")
        if getattr(approval, "session_id", None) != session.session_id:
            raise ValueError("approval is not bound to this session")
        if getattr(approval, "used_at", None):
            raise ValueError("approval has already been consumed")
        expires_at = getattr(approval, "expires_at", None)
        if expires_at and parse_iso(str(expires_at)) <= ensure_aware(
            self.clock()
        ):
            raise ValueError("approval has expired")
        decision_value = getattr(approval, "decision", None)
        if decision_value not in {"approved", "approve", True}:
            raise ValueError("approval decision is not approved")
        return self.record(
            user_id=session.customer_id,
            session_id=session.session_id,
            tool_name=tool_name,
            tool_version=tool_version,
            arguments=arguments,
            risk_level=str(getattr(decision, "tier", "unknown")),
            preview_hash=str(preview_hash),
            approval_id=str(getattr(approval, "approval_id", "")),
            ttl_seconds=ttl_seconds,
            metadata={"source": "bank_agent.risk.RiskComplianceEngine"},
        )

    def revoke(self, authorization_id: str, *, reason: str = "") -> bool:
        """Withdraw one authorization. Returns False when it was never issued."""
        now = iso(ensure_aware(self.clock()))
        with self._lock:
            evidence = self._items.get(authorization_id)
            if evidence is None:
                return False
            self._items[authorization_id] = replace(
                evidence, revoked_at=now, revoked_reason=str(reason)
            )
            return True

    def revoke_session(self, session_id: str, *, reason: str = "") -> int:
        """Withdraw every unused authorization bound to one session."""
        now = iso(ensure_aware(self.clock()))
        revoked = 0
        with self._lock:
            for key, evidence in list(self._items.items()):
                if evidence.session_id != session_id or evidence.revoked_at is not None:
                    continue
                self._items[key] = replace(
                    evidence, revoked_at=now, revoked_reason=str(reason)
                )
                revoked += 1
        return revoked

    def consume(
        self,
        request: RiskEvaluationRequest,
        *,
        policy_version: str | None = None,
    ) -> RiskAuthorizationEvidence | None:
        now = ensure_aware(self.clock())
        expected_policy = policy_version or self.expected_policy_version
        fingerprint = _arguments_hash(
            user_id=request.user_id,
            session_id=request.session_id,
            tool_name=request.tool_name,
            tool_version=request.tool_version,
            arguments=request.arguments,
        )
        with self._lock:
            for key, evidence in list(self._items.items()):
                # 已消费（重放）、已撤权、已过期、策略版本已变 → 一律不发证。
                if not evidence.is_usable(now):
                    continue
                if evidence.policy_version != expected_policy:
                    continue
                if (
                    evidence.user_id != request.user_id
                    or evidence.session_id != request.session_id
                    or evidence.tool_name != request.tool_name
                    or evidence.tool_version != request.tool_version
                    or evidence.arguments_hash != fingerprint
                ):
                    continue
                updated = replace(evidence, consumed_at=iso(now))
                self._items[key] = updated
                return updated
        return None


class ExistingRiskEngineAdapter(RiskEngineAdapter):
    """Bridge that consumes completed-engine approval evidence or refuses."""

    adapter_name = "Existing Risk Engine approval bridge"
    adapter_kind = "production"
    is_connected = True
    is_verified = False
    description = (
        "Requires a preview hash + approval ID evidence from the completed "
        "Risk Engine. Prepared but not verified; Module 6 stays fail-closed."
    )

    def __init__(
        self,
        registry: RiskAuthorizationRegistry | None = None,
        *,
        verified: bool = False,
        ticket: Any | None = None,
    ) -> None:
        self.registry = registry or RiskAuthorizationRegistry()
        self.ticket = ticket
        self.is_verified = bool(verified and ticket_covers(ticket, *VERIFICATION_SOURCES))

    def evaluate(self, request: RiskEvaluationRequest) -> RiskEvaluationResult:
        if not request.mutating:
            return RiskEvaluationResult(
                allowed=True,
                decision_id=new_id("RDEC"),
                risk_level="not_required",
                policy_version=SECURITY_POLICY_VERSION,
                reasons=("NON_MUTATING_TOOL",),
                metadata={"bridge": "existing_risk_engine"},
            )
        evidence = self.registry.consume(request)
        if evidence is None:
            return RiskEvaluationResult(
                allowed=False,
                decision_id=new_id("RDEC"),
                risk_level="unknown",
                requires_confirmation=True,
                requires_step_up=False,
                reasons=("NO_VERIFIED_RISK_AUTHORIZATION",),
                flags=("fail_closed",),
                policy_version=SECURITY_POLICY_VERSION,
                metadata={
                    "bridge": "existing_risk_engine",
                    "requires_preview_and_approval": True,
                },
            )
        return RiskEvaluationResult(
            allowed=True,
            decision_id=new_id("RDEC"),
            risk_level=evidence.risk_level,
            requires_confirmation=True,
            requires_step_up=evidence.risk_level == "R4",
            reasons=("EXISTING_RISK_APPROVAL_CONSUMED",),
            flags=(),
            policy_version=evidence.policy_version,
            metadata={
                "bridge": "existing_risk_engine",
                "authorization_id": evidence.authorization_id,
                "preview_hash": evidence.preview_hash,
                "approval_id": evidence.approval_id,
            },
        )


class WebApprovalEvidenceBridge:
    """Translate the web application's existing confirmation into Module 8 evidence.

    The web application already binds an operation to user, session, operation
    id, amount, ledger version, policy version and expiry, and re-checks that
    binding inside one SQLite transaction (`AgentService.bound_hash` /
    `check_pending`). This bridge does not re-derive any of that. The caller
    passes `verify_web_binding`, which must re-run the web application's own
    check inside the caller's transaction and return True. Only then is evidence
    recorded.

    Boundaries kept on purpose:

    - No second ledger is created. Nothing is written back to the web database.
    - The web preview hash is stored as the evidence preview hash and the web
      operation id as the approval id, so the two records stay traceable.
    - The TTL never exceeds the web preview's remaining lifetime.
    """

    WEB_POLICY_VERSION = "integrated-demo-1026.1"
    MAX_TTL_SECONDS = 300

    def __init__(
        self,
        registry: RiskAuthorizationRegistry,
        *,
        policy_version: str = WEB_POLICY_VERSION,
    ) -> None:
        self.registry = registry
        self.policy_version = policy_version

    def record_from_web_state(
        self,
        state: Mapping[str, Any],
        operation_id: str,
        *,
        tool_name: str,
        tool_version: str,
        arguments: Mapping[str, Any],
        verify_web_binding: Any,
    ) -> RiskAuthorizationEvidence:
        """Read one already-loaded web state dict and record evidence for it.

        The caller passes the state it just loaded inside its own SQLite
        transaction. This method never opens the web database.
        """
        operations = list(state.get("operations") or []) + list(
            state.get("transfer_ops") or []
        )
        op = next((item for item in operations if item.get("id") == operation_id), None)
        if op is None:
            raise LookupError("web operation not found")
        if op.get("type") != "transfer":
            raise NotImplementedError("web approval bridge only covers transfers")
        status = op.get("status")
        if status != "awaiting_confirmation":
            # 覆盖 unknown / succeeded / failed / cancelled / invalidated：
            # 未知回执不得借此重试扣款，也不得转成授权。
            raise PermissionError(f"web operation is not awaiting confirmation: {status}")
        if op.get("version") != state.get("version"):
            raise PermissionError("web operation ledger version is stale")
        return self.record_from_web_operation(
            user_id=str(state.get("customer_id") or ""),
            session_id=str(state.get("session_id") or ""),
            tool_name=tool_name,
            tool_version=tool_version,
            arguments=arguments,
            operation_id=operation_id,
            preview_hash=str(op.get("preview_hash") or ""),
            expires_at=op.get("expires_at"),
            verify_web_binding=verify_web_binding,
            risk_level="R4" if op.get("level") == "red" else "R3",
        )

    def record_from_web_operation(
        self,
        *,
        user_id: str,
        session_id: str,
        tool_name: str,
        tool_version: str,
        arguments: Mapping[str, Any],
        operation_id: str,
        preview_hash: str,
        expires_at: Any,
        verify_web_binding: Any,
        risk_level: str = "R4",
    ) -> RiskAuthorizationEvidence:
        if not callable(verify_web_binding):
            raise ValueError("web approval bridge requires a binding verifier")
        if not verify_web_binding():
            # 网页侧绑定不再成立（参数/版本/权限/过期），不得发证。
            raise PermissionError("web operation binding is no longer valid")
        if not preview_hash or not operation_id:
            raise ValueError("web approval needs a preview hash and operation id")

        now = ensure_aware(self.registry.clock())
        # 网页的 expires_at 是 epoch 秒整数；这里同时接受 ISO 字符串，避免把
        # 网页字段当成 Module 8 的 ISO 时间解析而误判。
        if isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool):
            expiry_dt = datetime.fromtimestamp(float(expires_at), timezone.utc)
        else:
            expiry_dt = parse_iso(str(expires_at))
        remaining = int(expiry_dt.timestamp() - now.timestamp())
        if remaining <= 0:
            raise PermissionError("web operation has expired")
        ttl = min(remaining, self.MAX_TTL_SECONDS)
        return self.registry.record(
            user_id=user_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_version=tool_version,
            arguments=arguments,
            risk_level=risk_level,
            preview_hash=str(preview_hash),
            approval_id=str(operation_id),
            ttl_seconds=ttl,
            policy_version=self.policy_version,
            metadata={
                "source": "web.ledger.operation",
                "web_operation_id": str(operation_id),
                "web_policy_version": self.policy_version,
            },
        )
