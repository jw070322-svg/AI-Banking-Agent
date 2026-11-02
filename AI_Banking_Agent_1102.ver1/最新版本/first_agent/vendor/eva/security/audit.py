"""Security event logging with mandatory redaction.

Security logs are an audit trail, not a debugging dump. They record:
- event type, category, decision, reason code, trace/event IDs;
- user/session identifiers (opaque session ID, never the bearer token);
- a non-reversible content hash for correlation;
- safe metadata only.

They never record passwords, OTPs, bearer tokens, CSRF tokens, full card
numbers, full account numbers, raw user text or raw retrieved content.

The completed ComplianceScanner is reused for PII/secret-key redaction so the
security layer does not maintain a competing redaction rule set.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import utc_now
from ..risk.compliance import ComplianceScanner
from .models import (
    Decision,
    Principal,
    SecurityDecision,
    SecurityEvent,
    new_security_id,
)


class AuditUnavailableError(RuntimeError):
    """Raised when a mandatory audit sink cannot record an event."""


class SecurityAuditSink(ABC):
    @abstractmethod
    def record(self, event: SecurityEvent) -> None:
        raise NotImplementedError

    def events(self) -> list[dict[str, Any]]:
        return []


class NullSecurityAudit(SecurityAuditSink):
    """Explicit no-op sink. Use only in isolated unit tests."""

    def record(self, event: SecurityEvent) -> None:
        return None


class InMemorySecurityAudit(SecurityAuditSink):
    def __init__(self) -> None:
        self._events: list[SecurityEvent] = []
        self._lock = threading.RLock()

    def record(self, event: SecurityEvent) -> None:
        with self._lock:
            self._events.append(event)

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return [event.to_dict() for event in self._events]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


class JsonlSecurityAudit(SecurityAuditSink):
    """Append-only JSONL sink with fsync.

    This is a demonstration audit channel, not WORM storage. Production must
    use a tamper-evident store with retention policy and access control.
    """

    def __init__(
        self,
        log_dir: str | Path,
        *,
        scanner: ComplianceScanner | None = None,
        filename: str | None = None,
    ) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.scanner = scanner or ComplianceScanner()
        self.filename = filename
        self._lock = threading.RLock()
        self._recent: list[dict[str, Any]] = []

    def _path(self) -> Path:
        if self.filename:
            return self.log_dir / self.filename
        stamp = datetime.now().strftime("%Y%m%d")
        return self.log_dir / f"security-{stamp}.jsonl"

    def record(self, event: SecurityEvent) -> None:
        payload = self.scanner.redact_obj(event.to_dict())
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        try:
            with self._lock:
                path = self._path()
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                self._recent.append(payload)
        except OSError as exc:
            raise AuditUnavailableError("security audit sink failed") from exc

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._recent)


class SecurityAuditLogger:
    """Builds safe events and sends them to a sink.

    Callers that are about to perform a state-changing operation should treat
    an `AuditUnavailableError` as a fail-closed condition.
    """

    def __init__(
        self,
        sink: SecurityAuditSink | None = None,
        *,
        scanner: ComplianceScanner | None = None,
    ) -> None:
        self.sink = sink if sink is not None else InMemorySecurityAudit()
        self.scanner = scanner or ComplianceScanner()

    def log(
        self,
        event_type: str,
        *,
        decision: SecurityDecision | None = None,
        principal: Principal | None = None,
        session_id: str | None = None,
        source: str = "",
        content: str | None = None,
        details: dict[str, Any] | None = None,
        category: str | None = None,
        outcome: str | None = None,
        reason_code: str | None = None,
    ) -> SecurityEvent:
        payload: dict[str, Any] = dict(details or {})
        if decision is not None:
            payload.setdefault("policy_version", decision.policy_version)
            payload.setdefault("requires_review", decision.requires_review)
        event = SecurityEvent(
            event_type=event_type,
            category=category or (decision.category if decision else "SECURITY"),
            decision=outcome or (
                decision.decision if decision else Decision.ALLOW.value
            ),
            reason_code=reason_code or (
                decision.reason_code if decision else "EVENT"
            ),
            trace_id=decision.trace_id if decision else new_security_id("TRACE"),
            user_id=principal.user_id if principal else None,
            session_id=session_id or (
                principal.session_id if principal else None
            ),
            source=source,
            content_hash=(
                hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
                if content
                else None
            ),
            details=self.scanner.redact_obj(payload),
        )
        self.sink.record(event)
        return event

    def try_log(self, *args: Any, **kwargs: Any) -> SecurityEvent | None:
        """Best-effort logging for non-critical events (e.g. failed login)."""
        try:
            return self.log(*args, **kwargs)
        except AuditUnavailableError:
            return None
