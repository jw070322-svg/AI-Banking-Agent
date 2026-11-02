"""Opaque server-side sessions and cookie/CSRF helpers.

Why opaque sessions instead of JWTs:
- immediate revocation on logout / account disable / permission change;
- no signing-key distribution or claim-validation mistakes in the demo;
- the server stores only a SHA-256 hash of the bearer token, so a read-only
  session-store leak does not expose usable credentials.

Trade-off: this demo store is in-process. A production deployment must move it
to a shared, durable store (e.g. Redis/DB) with the same hashing and expiry
semantics. If JWT is later required, the token validator must verify signature,
issuer, audience, exp, nbf and jti, and maintain a revocation list.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable

from .models import new_security_id
from ..models import utc_now


def utc_datetime() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def iso(value: datetime) -> str:
    return ensure_aware(value).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return ensure_aware(parsed)


def hash_token(token: str) -> str:
    """Hash a bearer/CSRF token for storage. Never store the raw value."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_fingerprint(token: str) -> str:
    """Short, non-reversible fingerprint safe for audit correlation."""
    return hash_token(token)[:12]


def generate_token(*, nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def generate_csrf_token(*, nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


@dataclass(frozen=True)
class SessionPolicy:
    idle_timeout_seconds: int = 900
    absolute_timeout_seconds: int = 28_800
    token_bytes: int = 32
    csrf_bytes: int = 32
    max_sessions_per_user: int = 3
    lockout_threshold: int = 5
    lockout_seconds: int = 900
    password_iterations: int = 210_000

    def __post_init__(self) -> None:
        if self.idle_timeout_seconds <= 0:
            raise ValueError("idle timeout must be positive")
        if self.absolute_timeout_seconds < self.idle_timeout_seconds:
            raise ValueError("absolute timeout must be >= idle timeout")
        if self.token_bytes < 32:
            raise ValueError("session tokens must use at least 32 random bytes")
        if self.csrf_bytes < 32:
            raise ValueError("CSRF tokens must use at least 32 random bytes")
        if self.max_sessions_per_user < 1:
            raise ValueError("max_sessions_per_user must be >= 1")
        if self.lockout_threshold < 1:
            raise ValueError("lockout_threshold must be >= 1")


@dataclass(frozen=True)
class SessionRecord:
    """Internal session record. `token_hash`/`csrf_hash` are not credentials."""

    session_id: str
    user_id: str
    token_hash: str
    csrf_hash: str
    roles: tuple[str, ...]
    auth_level: str
    transport: str
    created_at: str
    last_seen_at: str
    idle_expires_at: str
    absolute_expires_at: str
    permission_version: int
    device_id: str | None = None
    revoked_at: str | None = None

    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired(self, now: datetime) -> tuple[bool, str]:
        if now >= parse_iso(self.absolute_expires_at):
            return True, "absolute"
        if now >= parse_iso(self.idle_expires_at):
            return True, "idle"
        return False, ""


class SessionStore(ABC):
    @abstractmethod
    def create(self, record: SessionRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_by_token_hash(self, token_hash: str) -> SessionRecord | None:
        raise NotImplementedError

    @abstractmethod
    def update(self, record: SessionRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def revoke(self, session_id: str, *, at: str | None = None) -> bool:
        raise NotImplementedError

    @abstractmethod
    def revoke_user(self, user_id: str, *, at: str | None = None) -> int:
        raise NotImplementedError

    @abstractmethod
    def active_for_user(self, user_id: str) -> list[SessionRecord]:
        raise NotImplementedError


class InMemorySessionStore(SessionStore):
    """Thread-safe demo store. Not durable across process restarts."""

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}
        self._lock = threading.RLock()

    def create(self, record: SessionRecord) -> None:
        with self._lock:
            self._records[record.token_hash] = record

    def get_by_token_hash(self, token_hash: str) -> SessionRecord | None:
        with self._lock:
            return self._records.get(token_hash)

    def update(self, record: SessionRecord) -> None:
        with self._lock:
            if record.token_hash in self._records:
                self._records[record.token_hash] = record

    def revoke(self, session_id: str, *, at: str | None = None) -> bool:
        stamp = at or utc_now()
        with self._lock:
            for key, record in list(self._records.items()):
                if record.session_id == session_id:
                    if record.revoked_at is not None:
                        return True
                    self._records[key] = replace(record, revoked_at=stamp)
                    return True
        return False

    def revoke_user(self, user_id: str, *, at: str | None = None) -> int:
        stamp = at or utc_now()
        changed = 0
        with self._lock:
            for key, record in list(self._records.items()):
                if record.user_id == user_id and record.revoked_at is None:
                    self._records[key] = replace(record, revoked_at=stamp)
                    changed += 1
        return changed

    def active_for_user(self, user_id: str) -> list[SessionRecord]:
        now = utc_datetime()
        with self._lock:
            return [
                record
                for record in self._records.values()
                if record.user_id == user_id
                and record.revoked_at is None
                and not record.is_expired(now)[0]
            ]


class SessionFactory:
    """Creates session records with unpredictable identifiers and tokens."""

    def __init__(
        self,
        policy: SessionPolicy | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.policy = policy or SessionPolicy()
        self.clock = clock or utc_datetime

    def create(
        self,
        *,
        user_id: str,
        roles: tuple[str, ...],
        auth_level: str,
        permission_version: int,
        transport: str = "bearer",
        device_id: str | None = None,
    ) -> tuple[SessionRecord, str, str | None]:
        now = ensure_aware(self.clock())
        token = generate_token(nbytes=self.policy.token_bytes)
        csrf_token = (
            generate_csrf_token(nbytes=self.policy.csrf_bytes)
            if transport == "cookie"
            else None
        )
        session_id = new_security_id("SESS")
        record = SessionRecord(
            session_id=session_id,
            user_id=user_id,
            token_hash=hash_token(token),
            csrf_hash=hash_token(csrf_token) if csrf_token else "",
            roles=tuple(roles),
            auth_level=auth_level,
            transport=transport,
            created_at=iso(now),
            last_seen_at=iso(now),
            idle_expires_at=iso(
                now + timedelta(seconds=self.policy.idle_timeout_seconds)
            ),
            absolute_expires_at=iso(
                now + timedelta(seconds=self.policy.absolute_timeout_seconds)
            ),
            permission_version=permission_version,
            device_id=device_id,
        )
        return record, token, csrf_token

    def touch(self, record: SessionRecord) -> SessionRecord:
        now = ensure_aware(self.clock())
        idle_expires = now + timedelta(seconds=self.policy.idle_timeout_seconds)
        absolute = parse_iso(record.absolute_expires_at)
        if idle_expires > absolute:
            idle_expires = absolute
        return replace(
            record,
            last_seen_at=iso(now),
            idle_expires_at=iso(idle_expires),
        )


@dataclass(frozen=True)
class SessionCookiePolicy:
    """Cookie attributes for a browser transport adapter.

    The CLI demo uses a bearer token; the web adapter should set these flags.
    `__Host-` requires Secure, Path=/ and no Domain attribute.
    """

    name: str = "__Host-bank_session"
    path: str = "/"
    secure: bool = True
    httponly: bool = True
    samesite: str = "Strict"

    def __post_init__(self) -> None:
        if self.name.startswith("__Host-") and (
            not self.secure or self.path != "/"
        ):
            raise ValueError("__Host- cookies require Secure and Path=/")
        if self.samesite not in {"Strict", "Lax", "None"}:
            raise ValueError("invalid SameSite value")

    def set_cookie(self, token: str, *, max_age: int) -> str:
        return (
            f"{self.name}={token}; Path={self.path}; "
            f"Max-Age={int(max_age)}; HttpOnly; Secure; "
            f"SameSite={self.samesite}"
        )

    def clear_cookie(self) -> str:
        return (
            f"{self.name}=; Path={self.path}; Max-Age=0; "
            f"HttpOnly; Secure; SameSite={self.samesite}"
        )


def verify_csrf(record: SessionRecord, provided: str | None) -> bool:
    if not provided or not record.csrf_hash:
        return False
    return hmac.compare_digest(hash_token(provided), record.csrf_hash)
