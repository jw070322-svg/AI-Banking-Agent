"""Transaction-bound confirmation and revalidation.

This is a security admission control, not a replacement for the completed Risk
Engine's preview/approval lifecycle. The Risk Engine remains authoritative for
risk limits and risk decisions. Module 8 binds a confirmation to:

- the authenticated user and session;
- the exact action and server-resolved resource;
- exact transaction details (source, destination, amount, currency, note hash);
- a short expiry;
- single use, with an idempotency key derived from the binding.

A generic "yes", an earlier approval, or an LLM-generated statement is never
accepted as confirmation for a different transaction.
"""

from __future__ import annotations

import hashlib
import json
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ..models import utc_now
from .audit import SecurityAuditLogger
from .models import (
    Decision,
    Principal,
    ReasonCode,
    ResolvedResource,
    SecurityCategory,
    SecurityDecision,
    new_security_id,
)
from .sessions import ensure_aware, iso, parse_iso


# ----------------------------------------------------------------------
# Canonical binding
# ----------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def binding_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def _safe_display(value: Any, depth: int = 0) -> Any:
    """A bounded, redacted view for the confirmation card."""
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(key): _safe_display(item, depth + 1)
            for key, item in value.items()
            if str(key).lower()
            not in {
                "password",
                "token",
                "secret",
                "api_key",
                "private_key",
                "otp",
                "authorization",
                "note",
            }
        }
    if isinstance(value, (list, tuple)):
        return [_safe_display(item, depth + 1) for item in value][:20]
    if isinstance(value, str):
        return value if len(value) <= 120 else value[:120] + "…"
    return value


# ----------------------------------------------------------------------
# Step-up port
# ----------------------------------------------------------------------


class StepUpVerifier(ABC):
    """Optional step-up assertion verifier for critical confirmations.

    Production must implement this against the bank's OTP/biometric assertion
    service. The default is absent; a confirmation that requires step-up fails
    closed if no verifier is configured.
    """

    @abstractmethod
    def verify(
        self,
        *,
        user_id: str,
        session_id: str,
        binding_hash: str,
        assertion_id: str,
    ) -> bool:
        raise NotImplementedError


# ----------------------------------------------------------------------
# Records
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ConfirmationChallenge:
    confirmation_id: str
    user_id: str
    session_id: str
    action: str
    resource_id: str | None
    details: Mapping[str, Any]
    details_hash: str
    parameters_hash: str
    created_at: str
    expires_at: str
    requires_step_up: bool = False
    simulated: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "confirmation_id": self.confirmation_id,
            "action": self.action,
            "resource_id": self.resource_id,
            "details": _safe_display(dict(self.details)),
            "details_hash": self.details_hash,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "requires_step_up": self.requires_step_up,
            "simulated": self.simulated,
        }


@dataclass(frozen=True)
class ConfirmationRecord:
    confirmation_id: str
    user_id: str
    session_id: str
    action: str
    resource_id: str | None
    details: Mapping[str, Any]
    parameters: Mapping[str, Any]
    details_hash: str
    parameters_hash: str
    created_at: str
    expires_at: str
    requires_step_up: bool
    confirmed_at: str | None = None
    used_at: str | None = None
    step_up_verified: bool = False
    cancelled_at: str | None = None


@dataclass(frozen=True)
class ConfirmationResult:
    ok: bool
    decision: SecurityDecision
    challenge: ConfirmationChallenge | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "decision": self.decision.to_dict(),
            "challenge": self.challenge.to_dict() if self.challenge else None,
        }


@dataclass(frozen=True)
class ConsumptionResult:
    ok: bool
    decision: SecurityDecision
    idempotency_key: str | None = None
    details_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "decision": self.decision.to_dict(),
            "idempotency_key_present": bool(self.idempotency_key),
            "details_hash": self.details_hash,
        }


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------


class ConfirmationService:
    def __init__(
        self,
        *,
        ttl_seconds: int = 120,
        clock=None,
        step_up_verifier: StepUpVerifier | None = None,
        audit: SecurityAuditLogger | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("confirmation ttl must be positive")
        self.ttl_seconds = ttl_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.step_up_verifier = step_up_verifier
        self.audit = audit or SecurityAuditLogger()
        self._records: dict[str, ConfirmationRecord] = {}
        self._lock = threading.RLock()

    def prepare(
        self,
        principal: Principal,
        *,
        action: str,
        resource_id: str | None,
        parameters: Mapping[str, Any],
        display_details: Mapping[str, Any] | None = None,
        ttl_seconds: int | None = None,
        requires_step_up: bool = False,
    ) -> ConfirmationResult:
        trace_id = new_security_id("TRACE")
        if principal.account_status != "active":
            return ConfirmationResult(
                ok=False,
                decision=SecurityDecision.block(
                    SecurityCategory.CONFIRMATION.value,
                    ReasonCode.AUTH_ACCOUNT_DISABLED,
                    trace_id=trace_id,
                ),
            )
        if principal.auth_level not in {"strong", "step_up"}:
            return ConfirmationResult(
                ok=False,
                decision=SecurityDecision.block(
                    SecurityCategory.CONFIRMATION.value,
                    ReasonCode.AUTH_INSUFFICIENT_LEVEL,
                    trace_id=trace_id,
                ),
            )
        if not action or not isinstance(parameters, Mapping):
            return ConfirmationResult(
                ok=False,
                decision=SecurityDecision.block(
                    SecurityCategory.CONFIRMATION.value,
                    ReasonCode.CONFIRMATION_INVALID,
                    trace_id=trace_id,
                ),
            )

        now = ensure_aware(self.clock())
        ttl = int(ttl_seconds or self.ttl_seconds)
        expires = now + timedelta(seconds=ttl)
        confirmation_id = new_security_id("CONF")
        details = dict(display_details or parameters)
        record = ConfirmationRecord(
            confirmation_id=confirmation_id,
            user_id=principal.user_id,
            session_id=principal.session_id,
            action=action,
            resource_id=resource_id,
            details=dict(details),
            parameters=dict(parameters),
            details_hash=binding_hash(details),
            parameters_hash=binding_hash(parameters),
            created_at=iso(now),
            expires_at=iso(expires),
            requires_step_up=bool(requires_step_up),
        )
        with self._lock:
            self._records[confirmation_id] = record

        challenge = self._challenge(record)
        decision = SecurityDecision.allow(
            SecurityCategory.CONFIRMATION.value,
            "CONFIRMATION_CHALLENGE_ISSUED",
            message="已生成一次性确认，请在有效期内确认。",
            trace_id=trace_id,
            details={
                "confirmation_id": confirmation_id,
                "action": action,
                "expires_at": record.expires_at,
                "requires_step_up": record.requires_step_up,
            },
        )
        self.audit.try_log(
            "CONFIRMATION_PREPARED",
            decision=decision,
            principal=principal,
            source="confirmation",
            details={"action": action, "resource_id": resource_id},
        )
        return ConfirmationResult(ok=True, decision=decision, challenge=challenge)

    def confirm(
        self,
        principal: Principal,
        confirmation_id: str,
        *,
        presented_details: Mapping[str, Any] | None = None,
        step_up_assertion_id: str | None = None,
    ) -> ConfirmationResult:
        trace_id = new_security_id("TRACE")
        record = self._get(confirmation_id)
        decision = self._validate_record(
            principal, record, trace_id, require_confirmed=False
        )
        if decision is not None:
            return ConfirmationResult(ok=False, decision=decision)

        assert record is not None
        if record.cancelled_at:
            return ConfirmationResult(
                ok=False,
                decision=SecurityDecision.block(
                    SecurityCategory.CONFIRMATION.value,
                    ReasonCode.CONFIRMATION_INVALID,
                    trace_id=trace_id,
                ),
            )
        if record.used_at:
            return ConfirmationResult(
                ok=False,
                decision=SecurityDecision.block(
                    SecurityCategory.CONFIRMATION.value,
                    ReasonCode.CONFIRMATION_ALREADY_USED,
                    trace_id=trace_id,
                ),
            )
        if presented_details is not None and binding_hash(
            dict(presented_details)
        ) != record.details_hash:
            return ConfirmationResult(
                ok=False,
                decision=SecurityDecision.block(
                    SecurityCategory.CONFIRMATION.value,
                    ReasonCode.CONFIRMATION_DETAILS_MISMATCH,
                    message="确认内容与当前交易不一致，请重新确认。",
                    trace_id=trace_id,
                ),
            )

        step_up_verified = record.step_up_verified
        if record.requires_step_up and not step_up_verified:
            if (
                self.step_up_verifier is None
                or not step_up_assertion_id
                or not self.step_up_verifier.verify(
                    user_id=principal.user_id,
                    session_id=principal.session_id,
                    binding_hash=record.details_hash,
                    assertion_id=step_up_assertion_id,
                )
            ):
                return ConfirmationResult(
                    ok=False,
                    decision=SecurityDecision.block(
                        SecurityCategory.CONFIRMATION.value,
                        ReasonCode.AUTH_INSUFFICIENT_LEVEL,
                        message="该操作需要更强的身份验证。",
                        trace_id=trace_id,
                    ),
                )
            step_up_verified = True

        now = iso(ensure_aware(self.clock()))
        if record.confirmed_at is None or step_up_verified != record.step_up_verified:
            with self._lock:
                current = self._records.get(confirmation_id)
                if current is not None:
                    self._records[confirmation_id] = replace(
                        current,
                        confirmed_at=current.confirmed_at or now,
                        step_up_verified=step_up_verified,
                    )
        decision = SecurityDecision.allow(
            SecurityCategory.CONFIRMATION.value,
            "CONFIRMATION_ACCEPTED",
            message="确认已记录。",
            trace_id=trace_id,
            details={"confirmation_id": confirmation_id, "action": record.action},
        )
        self.audit.try_log(
            "CONFIRMATION_ACCEPTED",
            decision=decision,
            principal=principal,
            source="confirmation",
            details={"action": record.action, "resource_id": record.resource_id},
        )
        return ConfirmationResult(
            ok=True, decision=decision, challenge=self._challenge(record)
        )

    def consume(
        self,
        principal: Principal,
        confirmation_id: str,
        *,
        action: str,
        resource_id: str | None,
        parameters: Mapping[str, Any],
    ) -> ConsumptionResult:
        trace_id = new_security_id("TRACE")
        record = self._get(confirmation_id)
        decision = self._validate_record(
            principal, record, trace_id, require_confirmed=True
        )
        if decision is not None:
            return ConsumptionResult(ok=False, decision=decision)

        assert record is not None
        if record.used_at:
            return ConsumptionResult(
                ok=False,
                decision=SecurityDecision.block(
                    SecurityCategory.CONFIRMATION.value,
                    ReasonCode.DUPLICATE_EXECUTION,
                    message="该确认已被使用，不能重复执行。",
                    trace_id=trace_id,
                ),
            )
        if record.action != action or record.resource_id != resource_id:
            return ConsumptionResult(
                ok=False,
                decision=SecurityDecision.block(
                    SecurityCategory.CONFIRMATION.value,
                    ReasonCode.CONFIRMATION_DETAILS_MISMATCH,
                    message="确认与当前操作不匹配。",
                    trace_id=trace_id,
                ),
            )
        if binding_hash(dict(parameters)) != record.parameters_hash:
            return ConsumptionResult(
                ok=False,
                decision=SecurityDecision.block(
                    SecurityCategory.CONFIRMATION.value,
                    ReasonCode.CONFIRMATION_DETAILS_MISMATCH,
                    message="交易要素已变化，请重新确认。",
                    trace_id=trace_id,
                ),
            )

        used_at = iso(ensure_aware(self.clock()))
        with self._lock:
            current = self._records.get(confirmation_id)
            if current is None or current.used_at is not None:
                return ConsumptionResult(
                    ok=False,
                    decision=SecurityDecision.block(
                        SecurityCategory.CONFIRMATION.value,
                        ReasonCode.DUPLICATE_EXECUTION,
                        trace_id=trace_id,
                    ),
                )
            self._records[confirmation_id] = replace(current, used_at=used_at)

        idempotency_key = "sec:" + hashlib.sha256(
            (
                f"{record.user_id}|{record.session_id}|"
                f"{confirmation_id}|{record.parameters_hash}"
            ).encode("utf-8")
        ).hexdigest()[:40]
        decision = SecurityDecision.allow(
            SecurityCategory.CONFIRMATION.value,
            "CONFIRMATION_CONSUMED",
            message="确认已消费。",
            trace_id=trace_id,
            details={"confirmation_id": confirmation_id, "action": action},
        )
        self.audit.try_log(
            "CONFIRMATION_CONSUMED",
            decision=decision,
            principal=principal,
            source="confirmation",
            details={"action": action, "resource_id": resource_id},
        )
        return ConsumptionResult(
            ok=True,
            decision=decision,
            idempotency_key=idempotency_key,
            details_hash=record.parameters_hash,
        )

    def cancel(self, principal: Principal, confirmation_id: str) -> ConfirmationResult:
        trace_id = new_security_id("TRACE")
        record = self._get(confirmation_id)
        if record is None or record.user_id != principal.user_id:
            return ConfirmationResult(
                ok=False,
                decision=SecurityDecision.block(
                    SecurityCategory.CONFIRMATION.value,
                    ReasonCode.CONFIRMATION_INVALID,
                    trace_id=trace_id,
                ),
            )
        with self._lock:
            current = self._records.get(confirmation_id)
            if current is not None and current.used_at is None:
                self._records[confirmation_id] = replace(
                    current, cancelled_at=iso(ensure_aware(self.clock()))
                )
        return ConfirmationResult(
            ok=True,
            decision=SecurityDecision.allow(
                SecurityCategory.CONFIRMATION.value,
                "CONFIRMATION_CANCELLED",
                trace_id=trace_id,
            ),
        )

    def get_challenge(
        self, principal: Principal, confirmation_id: str
    ) -> ConfirmationChallenge | None:
        record = self._get(confirmation_id)
        if record is None or record.user_id != principal.user_id:
            return None
        return self._challenge(record)

    # ------------------------------------------------------------------
    # Transaction helper
    # ------------------------------------------------------------------

    def prepare_transaction(
        self,
        principal: Principal,
        *,
        source: ResolvedResource,
        beneficiary: ResolvedResource,
        amount: str,
        currency: str,
        note: str = "",
        ttl_seconds: int | None = None,
        requires_step_up: bool = False,
    ) -> ConfirmationResult:
        try:
            normalized_amount = str(
                Decimal(str(amount)).quantize(Decimal("0.01"))
            )
        except (InvalidOperation, ValueError):
            normalized_amount = str(amount)
        normalized_currency = (currency or "").upper()
        details = {
            "type": "transaction",
            "amount": normalized_amount,
            "currency": normalized_currency,
            "from_account": source.label,
            "from_account_id": source.resource_id,
            "to_beneficiary": beneficiary.label,
            "to_beneficiary_id": beneficiary.resource_id,
            "note_hash": hashlib.sha256(note.encode("utf-8")).hexdigest()[:16]
            if note
            else None,
        }
        parameters = {
            "type": "transaction",
            "amount": normalized_amount,
            "currency": normalized_currency,
            "from_account_id": source.resource_id,
            "beneficiary_id": beneficiary.resource_id,
            "note_hash": details["note_hash"],
        }
        return self.prepare(
            principal,
            action="transaction.execute",
            resource_id=source.resource_id,
            parameters=parameters,
            display_details=details,
            ttl_seconds=ttl_seconds,
            requires_step_up=requires_step_up,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get(self, confirmation_id: str) -> ConfirmationRecord | None:
        if not confirmation_id:
            return None
        with self._lock:
            return self._records.get(confirmation_id)

    def _validate_record(
        self,
        principal: Principal,
        record: ConfirmationRecord | None,
        trace_id: str,
        *,
        require_confirmed: bool,
    ) -> SecurityDecision | None:
        if record is None:
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.CONFIRMATION_INVALID,
                trace_id=trace_id,
            )
        if (
            record.user_id != principal.user_id
            or record.session_id != principal.session_id
        ):
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.CONFIRMATION_INVALID,
                trace_id=trace_id,
            )
        if record.cancelled_at:
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.CONFIRMATION_INVALID,
                trace_id=trace_id,
            )
        now = ensure_aware(self.clock())
        if now >= parse_iso(record.expires_at):
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.CONFIRMATION_EXPIRED,
                message="确认已过期，请重新发起。",
                trace_id=trace_id,
            )
        if require_confirmed and record.confirmed_at is None:
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.CONFIRMATION_REQUIRED,
                message="该操作需要明确确认。",
                trace_id=trace_id,
            )
        return None

    @staticmethod
    def _challenge(record: ConfirmationRecord) -> ConfirmationChallenge:
        return ConfirmationChallenge(
            confirmation_id=record.confirmation_id,
            user_id=record.user_id,
            session_id=record.session_id,
            action=record.action,
            resource_id=record.resource_id,
            details=record.details,
            details_hash=record.details_hash,
            parameters_hash=record.parameters_hash,
            created_at=record.created_at,
            expires_at=record.expires_at,
            requires_step_up=record.requires_step_up,
        )


# ----------------------------------------------------------------------
# Transaction security policy
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class TransactionSecurityLimits:
    """Independent security limits, not a replacement for Risk Engine policy.

    `max_single_amount=None` means "delegated to the completed Risk Engine".
    If configured, this is a defence-in-depth ceiling that can only deny, never
    approve, a transaction the Risk Engine would reject.
    """

    allowed_currencies: frozenset[str] = frozenset({"CNY"})
    max_single_amount: str | None = None
    min_amount: str = "0.01"
    require_owned_source: bool = True
    require_known_beneficiary: bool = True


class TransactionSecurityPolicy:
    def __init__(self, limits: TransactionSecurityLimits | None = None) -> None:
        self.limits = limits or TransactionSecurityLimits()

    def validate(
        self,
        principal: Principal,
        *,
        source: ResolvedResource,
        beneficiary: ResolvedResource,
        amount: str | int | Decimal,
        currency: str,
    ) -> SecurityDecision:
        trace_id = new_security_id("TRACE")
        try:
            value = Decimal(str(amount))
        except (InvalidOperation, ValueError):
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.INVALID_TRANSACTION_DETAILS,
                trace_id=trace_id,
                details={"field": "amount"},
            )
        if not value.is_finite() or value <= 0:
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.INVALID_TRANSACTION_DETAILS,
                trace_id=trace_id,
                details={"field": "amount"},
            )
        try:
            quantized = value.quantize(Decimal("0.01"))
        except InvalidOperation:
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.INVALID_TRANSACTION_DETAILS,
                trace_id=trace_id,
                details={"field": "amount_precision"},
            )
        if value != quantized:
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.INVALID_TRANSACTION_DETAILS,
                trace_id=trace_id,
                details={"field": "amount_precision"},
            )
        minimum = Decimal(self.limits.min_amount)
        if value < minimum:
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.INVALID_TRANSACTION_DETAILS,
                trace_id=trace_id,
                details={"field": "amount_minimum"},
            )
        currency_value = (currency or "").upper()
        if currency_value not in self.limits.allowed_currencies:
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.CURRENCY_NOT_ALLOWED,
                details={"currency": currency_value},
                trace_id=trace_id,
            )
        if (
            self.limits.require_owned_source
            and source.owner_id != principal.user_id
        ):
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.RESOURCE_FORBIDDEN,
                trace_id=trace_id,
                details={"resource": "source"},
            )
        if (
            self.limits.require_known_beneficiary
            and beneficiary.owner_id != principal.user_id
        ):
            return SecurityDecision.block(
                SecurityCategory.CONFIRMATION.value,
                ReasonCode.RESOURCE_FORBIDDEN,
                trace_id=trace_id,
                details={"resource": "beneficiary"},
            )
        limit_configured = self.limits.max_single_amount is not None
        if limit_configured:
            maximum = Decimal(str(self.limits.max_single_amount))
            if value > maximum:
                return SecurityDecision.block(
                    SecurityCategory.CONFIRMATION.value,
                    ReasonCode.TRANSACTION_LIMIT_EXCEEDED,
                    message="交易金额超过安全上限，已被拦截。",
                    trace_id=trace_id,
                    details={
                        "limit_configured": True,
                        "limit_source": "module8_security_ceiling",
                    },
                )
        return SecurityDecision.allow(
            SecurityCategory.CONFIRMATION.value,
            "TRANSACTION_DETAILS_VALIDATED",
            message="交易要素通过安全检查。",
            trace_id=trace_id,
            details={
                "amount": str(value.quantize(Decimal("0.01"))),
                "currency": currency_value,
                "source": source.label,
                "beneficiary": beneficiary.label,
                "limit_configured": limit_configured,
                "limit_source": (
                    "module8_security_ceiling"
                    if limit_configured
                    else "delegated_to_risk_engine"
                ),
            },
        )
