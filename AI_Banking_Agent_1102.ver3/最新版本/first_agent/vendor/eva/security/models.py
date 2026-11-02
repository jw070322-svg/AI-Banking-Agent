"""Module 8 security domain models.

The security layer has its own decision vocabulary so that authentication,
authorization, injection screening and confirmation results are never confused
with the completed Risk Engine's `RiskDecision` or the Compliance Guard's
`ComplianceReport`.

Nothing in this module stores raw credentials, session tokens or untrusted text
in a decision object. `details` is reserved for safe, machine-readable metadata
(reason codes, counts, permission names, resource types).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4

from ..models import utc_now

SECURITY_POLICY_VERSION = "sec_2026_10_29"


def new_security_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10].upper()}"


# ----------------------------------------------------------------------
# Decisions
# ----------------------------------------------------------------------


class Decision(str, Enum):
    """Security-screening / access outcomes.

    Kept deliberately separate from the Risk Engine's risk tiers and the
    Compliance Guard's findings.
    """

    ALLOW = "ALLOW"
    RESTRICT = "RESTRICT"
    REQUIRE_REVIEW = "REQUIRE_REVIEW"
    BLOCK = "BLOCK"


class SecurityCategory(str, Enum):
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    SCREENING = "SCREENING"
    CONFIRMATION = "CONFIRMATION"
    OUTPUT = "OUTPUT"
    DEPENDENCY = "DEPENDENCY"


class ReasonCode:
    """Stable, machine-readable reason codes.

    New codes may be added; callers must treat unknown codes as a denial.
    """

    # Authentication / session
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_ACCOUNT_LOCKED = "AUTH_ACCOUNT_LOCKED"
    AUTH_ACCOUNT_DISABLED = "AUTH_ACCOUNT_DISABLED"
    AUTH_SESSION_INVALID = "AUTH_SESSION_INVALID"
    AUTH_SESSION_EXPIRED = "AUTH_SESSION_EXPIRED"
    AUTH_SESSION_REVOKED = "AUTH_SESSION_REVOKED"
    AUTH_INSUFFICIENT_LEVEL = "AUTH_INSUFFICIENT_LEVEL"
    AUTH_CSRF_INVALID = "AUTH_CSRF_INVALID"

    # Authorization
    INSUFFICIENT_PERMISSION = "INSUFFICIENT_PERMISSION"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    RESOURCE_REQUIRED = "RESOURCE_REQUIRED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_FORBIDDEN = "RESOURCE_FORBIDDEN"
    PERMISSION_CHANGED = "PERMISSION_CHANGED"
    ADMIN_GRANT_REQUIRED = "ADMIN_GRANT_REQUIRED"

    # Screening
    PROMPT_INJECTION_DETECTED = "PROMPT_INJECTION_DETECTED"
    INSTRUCTION_OVERRIDE = "INSTRUCTION_OVERRIDE"
    SYSTEM_PROMPT_EXTRACTION = "SYSTEM_PROMPT_EXTRACTION"
    SECRET_EXFILTRATION_ATTEMPT = "SECRET_EXFILTRATION_ATTEMPT"
    UNAUTHORIZED_TOOL_INVOCATION = "UNAUTHORIZED_TOOL_INVOCATION"
    CONFIRMATION_BYPASS_ATTEMPT = "CONFIRMATION_BYPASS_ATTEMPT"
    CROSS_TENANT_ACCESS_ATTEMPT = "CROSS_TENANT_ACCESS_ATTEMPT"
    OBFUSCATED_CONTENT = "OBFUSCATED_CONTENT"
    UNTRUSTED_INSTRUCTION = "UNTRUSTED_INSTRUCTION"
    SUSPICIOUS_CONTENT = "SUSPICIOUS_CONTENT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    RESTRICTED_CAPABILITY = "RESTRICTED_CAPABILITY"
    SCREENING_CONTEXT_REQUIRED = "SCREENING_CONTEXT_REQUIRED"
    BENIGN_SECURITY_TOPIC = "BENIGN_SECURITY_TOPIC"
    CONTENT_QUARANTINED = "CONTENT_QUARANTINED"

    # Confirmation / transaction
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    CONFIRMATION_INVALID = "CONFIRMATION_INVALID"
    CONFIRMATION_EXPIRED = "CONFIRMATION_EXPIRED"
    CONFIRMATION_ALREADY_USED = "CONFIRMATION_ALREADY_USED"
    CONFIRMATION_DETAILS_MISMATCH = "CONFIRMATION_DETAILS_MISMATCH"
    TRANSACTION_LIMIT_EXCEEDED = "TRANSACTION_LIMIT_EXCEEDED"
    CURRENCY_NOT_ALLOWED = "CURRENCY_NOT_ALLOWED"
    INVALID_TRANSACTION_DETAILS = "INVALID_TRANSACTION_DETAILS"
    DUPLICATE_EXECUTION = "DUPLICATE_EXECUTION"

    # Tool integration / output
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    TOOL_EXECUTION_DENIED = "TOOL_EXECUTION_DENIED"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    UNTRUSTED_TOOL_OUTPUT = "UNTRUSTED_TOOL_OUTPUT"
    SENSITIVE_OUTPUT_BLOCKED = "SENSITIVE_OUTPUT_BLOCKED"
    OUTPUT_REDACTED = "OUTPUT_REDACTED"

    # Dependencies
    SECURITY_DEPENDENCY_UNAVAILABLE = "SECURITY_DEPENDENCY_UNAVAILABLE"
    SECURITY_AUDIT_UNAVAILABLE = "SECURITY_AUDIT_UNAVAILABLE"


GENERIC_MESSAGES = {
    "AUTHENTICATION": "认证失败，请重新登录。",
    "AUTHORIZATION": "该操作无权执行。",
    "SCREENING": "该请求无法安全处理，已被安全策略拦截。",
    "CONFIRMATION": "确认无效、已过期或与当前操作不匹配。",
    "OUTPUT": "返回内容未通过安全检查，已被拦截。",
    "DEPENDENCY": "必需的安全控制不可用，操作已停止。",
}


@dataclass(frozen=True)
class SecurityDecision:
    """Standardized, machine-readable security decision envelope."""

    allowed: bool
    decision: str
    reason_code: str
    message: str
    category: str
    trace_id: str = field(default_factory=lambda: new_security_id("TRACE"))
    details: Mapping[str, Any] = field(default_factory=dict)
    policy_version: str = SECURITY_POLICY_VERSION
    timestamp: str = field(default_factory=utc_now)
    event_id: str = field(default_factory=lambda: new_security_id("SEC"))
    retryable: bool = False
    requires_review: bool = False

    def __post_init__(self) -> None:
        if self.decision not in {item.value for item in Decision}:
            raise ValueError(f"unknown security decision: {self.decision}")
        if self.decision in {Decision.ALLOW.value, Decision.RESTRICT.value}:
            expected = True
        else:
            expected = False
        if self.allowed is not expected:
            raise ValueError("allowed does not match decision")

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "message": self.message,
            "category": self.category,
            "trace_id": self.trace_id,
            "event_id": self.event_id,
            "details": _safe_details(self.details),
            "policy_version": self.policy_version,
            "timestamp": self.timestamp,
            "retryable": self.retryable,
            "requires_review": self.requires_review,
        }

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def allow(
        cls,
        category: str,
        reason_code: str = "ALLOWED",
        *,
        message: str = "允许执行。",
        trace_id: str | None = None,
        details: Mapping[str, Any] | None = None,
        requires_review: bool = False,
    ) -> "SecurityDecision":
        return cls(
            allowed=True,
            decision=Decision.ALLOW.value,
            reason_code=reason_code,
            message=message,
            category=category,
            trace_id=trace_id or new_security_id("TRACE"),
            details=details or {},
            requires_review=requires_review,
        )

    @classmethod
    def restrict(
        cls,
        category: str,
        reason_code: str,
        *,
        message: str | None = None,
        trace_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "SecurityDecision":
        return cls(
            allowed=True,
            decision=Decision.RESTRICT.value,
            reason_code=reason_code,
            message=message or GENERIC_MESSAGES.get(category, "操作受限。"),
            category=category,
            trace_id=trace_id or new_security_id("TRACE"),
            details=details or {},
        )

    @classmethod
    def review(
        cls,
        category: str,
        reason_code: str = ReasonCode.REVIEW_REQUIRED,
        *,
        message: str | None = None,
        trace_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> "SecurityDecision":
        return cls(
            allowed=False,
            decision=Decision.REQUIRE_REVIEW.value,
            reason_code=reason_code,
            message=message or "该请求需要人工复核后才能继续。",
            category=category,
            trace_id=trace_id or new_security_id("TRACE"),
            details=details or {},
            requires_review=True,
        )

    @classmethod
    def block(
        cls,
        category: str,
        reason_code: str,
        *,
        message: str | None = None,
        trace_id: str | None = None,
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
        requires_review: bool = False,
    ) -> "SecurityDecision":
        return cls(
            allowed=False,
            decision=Decision.BLOCK.value,
            reason_code=reason_code,
            message=message or GENERIC_MESSAGES.get(category, "操作已被拦截。"),
            category=category,
            trace_id=trace_id or new_security_id("TRACE"),
            details=details or {},
            retryable=retryable,
            requires_review=requires_review,
        )


def fail_closed(
    category: str = SecurityCategory.DEPENDENCY.value,
    reason_code: str = ReasonCode.SECURITY_DEPENDENCY_UNAVAILABLE,
    *,
    details: Mapping[str, Any] | None = None,
    trace_id: str | None = None,
) -> SecurityDecision:
    """Fail-closed decision used when a mandatory control is unavailable."""
    return SecurityDecision.block(
        category,
        reason_code,
        message=GENERIC_MESSAGES["DEPENDENCY"],
        details=details or {},
        trace_id=trace_id,
    )


def _safe_details(value: Any, depth: int = 0) -> Any:
    """Defensive copy for decision details.

    Security decisions must never carry raw user text, credentials, tokens or
    full financial records. Callers are expected to put only metadata here; this
    function adds a last line of defence for accidental long strings.
    """
    if depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(key): _safe_details(item, depth + 1)
            for key, item in value.items()
            if str(key).lower()
            not in {
                "password",
                "passcode",
                "otp",
                "token",
                "access_token",
                "refresh_token",
                "secret",
                "api_key",
                "private_key",
                "authorization",
                "cookie",
                "csrf",
                "csrf_token",
                "session_token",
                "raw_content",
                "matched",
            }
        }
    if isinstance(value, (list, tuple)):
        return [_safe_details(item, depth + 1) for item in value]
    if isinstance(value, str):
        # Long free text is never needed in a security decision.
        if len(value) > 200:
            return value[:200] + "…"
        return value
    return value


# ----------------------------------------------------------------------
# Identity and session
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """A server-derived authenticated identity.

    The LLM, the client and tool arguments can never construct a trusted
    Principal. It is only produced by `MockAuthenticationProvider` after
    credential/session verification.
    """

    user_id: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    auth_level: str = "strong"
    session_id: str = ""
    account_status: str = "active"
    permission_version: int = 1
    device_id: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.roles, (list, set)):
            object.__setattr__(self, "roles", tuple(self.roles))
        if isinstance(self.permissions, (list, set, tuple)):
            object.__setattr__(self, "permissions", frozenset(self.permissions))

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def has_any(self, permissions: frozenset[str] | set[str]) -> bool:
        return bool(self.permissions & set(permissions))

    def public_dict(self) -> dict[str, Any]:
        """Principal fields safe for a security event.

        No token, password or CSRF value is present.
        """
        return {
            "user_id": self.user_id,
            "roles": list(self.roles),
            "permissions": sorted(self.permissions),
            "auth_level": self.auth_level,
            "session_id": self.session_id,
            "account_status": self.account_status,
            "permission_version": self.permission_version,
        }


@dataclass(frozen=True)
class AuthSession:
    """Safe session view returned after login/validation."""

    principal: Principal
    session_id: str
    issued_at: str
    idle_expires_at: str
    absolute_expires_at: str
    transport: str = "bearer"
    device_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "principal": self.principal.public_dict(),
            "issued_at": self.issued_at,
            "idle_expires_at": self.idle_expires_at,
            "absolute_expires_at": self.absolute_expires_at,
            "transport": self.transport,
            "device_id": self.device_id,
        }


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    decision: SecurityDecision
    session: AuthSession | None = None
    token: str | None = field(default=None, repr=False)
    csrf_token: str | None = field(default=None, repr=False)

    def to_dict(self, *, include_token: bool = False) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "decision": self.decision.to_dict(),
            "session": self.session.public_dict() if self.session else None,
        }
        if include_token:
            # Only for the transport adapter that sets an HttpOnly cookie.
            # Never write this value to a log.
            payload["token"] = self.token
            payload["csrf_token"] = self.csrf_token
        return payload


@dataclass(frozen=True)
class SessionValidation:
    ok: bool
    decision: SecurityDecision
    session: AuthSession | None = None

    @property
    def principal(self) -> Principal | None:
        return self.session.principal if self.session else None


# ----------------------------------------------------------------------
# Resources
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceRef:
    """A resource reference supplied by a caller or an LLM.

    `id` is untrusted input. It is resolved against server-side ownership
    before use; never interpreted directly as an authorization fact.
    """

    type: str
    id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {"type": self.type, "id": self.id}


@dataclass(frozen=True)
class ResolvedResource:
    """Server-resolved resource with a trusted owner."""

    type: str
    resource_id: str
    owner_id: str
    label: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "resource_id": self.resource_id,
            "label": self.label,
        }


# ----------------------------------------------------------------------
# Findings / events
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class SecurityFinding:
    """A safe description of a suspicious signal.

    `matched` text is intentionally not stored; only a code, severity and
    generic detail are kept so logs and API responses cannot echo malicious
    content or secrets.
    """

    code: str
    category: str
    severity: str  # low / medium / high / critical
    confidence: float
    detail: str
    action: str = "allow"  # allow / restrict / review / block

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "severity": self.severity,
            "confidence": round(float(self.confidence), 3),
            "detail": self.detail,
            "action": self.action,
        }


@dataclass(frozen=True)
class SecurityEvent:
    """Audit-safe security event. Raw content/credentials are never included."""

    event_type: str
    category: str
    decision: str
    reason_code: str
    trace_id: str
    timestamp: str = field(default_factory=utc_now)
    event_id: str = field(default_factory=lambda: new_security_id("SEV"))
    user_id: str | None = None
    session_id: str | None = None
    source: str = ""
    content_hash: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "category": self.category,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "source": self.source,
            "content_hash": self.content_hash,
            "details": _safe_details(self.details),
        }
