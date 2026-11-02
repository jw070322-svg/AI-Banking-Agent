"""Authentication provider interface and a clearly-labelled development mock.

There is no existing identity provider in this repository. This module fills the
gap with an in-memory provider suitable for demos/tests only:

- PBKDF2-HMAC-SHA256 password records, per-user random salts;
- unpredictable opaque session tokens, only SHA-256 hashes stored server-side;
- idle + absolute session expiry, logout/revocation, per-user session cap;
- failed-attempt lockout and account-status checks;
- generic user-facing failure messages and redacted security events.

It is not an SSO/OIDC implementation and must be replaced by the bank's real
identity provider in production. See docs/MODULE_8_SECURITY.md.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from ..models import utc_now
from .audit import AuditUnavailableError, SecurityAuditLogger
from .authorization import permissions_for_roles
from .models import (
    AuthSession,
    LoginResult,
    Principal,
    ReasonCode,
    SecurityCategory,
    SecurityDecision,
    SessionValidation,
    fail_closed,
    new_security_id,
)
from .passwords import PasswordRecord, dummy_verify, hash_password, verify_password
from .sessions import (
    InMemorySessionStore,
    SessionFactory,
    SessionPolicy,
    SessionRecord,
    SessionStore,
    ensure_aware,
    hash_token,
    iso,
    parse_iso,
    verify_csrf,
)


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str = field(repr=False)

    def __repr__(self) -> str:  # never leak a password through repr/format
        return f"Credentials(username={self.username!r}, password='[REDACTED]')"


@dataclass(frozen=True)
class UserSeed:
    user_id: str
    username: str
    password: str = field(repr=False)
    roles: tuple[str, ...] = ("customer",)
    status: str = "active"  # active / disabled
    auth_level: str = "strong"

    def __post_init__(self) -> None:
        if isinstance(self.roles, (list, set)):
            object.__setattr__(self, "roles", tuple(self.roles))

    def __repr__(self) -> str:
        return (
            f"UserSeed(user_id={self.user_id!r}, username={self.username!r}, "
            f"roles={self.roles!r}, status={self.status!r}, "
            f"password='[REDACTED]')"
        )


@dataclass
class _UserRecord:
    user_id: str
    username: str
    password: PasswordRecord
    roles: tuple[str, ...]
    status: str
    auth_level: str
    failed_attempts: int = 0
    locked_until: str | None = None
    permission_version: int = 1


class AuthenticationProvider(ABC):
    @abstractmethod
    def authenticate(
        self,
        credentials: Credentials,
        *,
        device_id: str | None = None,
        transport: str = "bearer",
    ) -> LoginResult:
        raise NotImplementedError

    @abstractmethod
    def validate_session(
        self,
        token: str,
        *,
        require_csrf: str | None = None,
    ) -> SessionValidation:
        raise NotImplementedError

    @abstractmethod
    def logout(self, token: str) -> SecurityDecision:
        raise NotImplementedError

    @abstractmethod
    def revoke_user_sessions(self, user_id: str) -> int:
        raise NotImplementedError


class MockAuthenticationProvider(AuthenticationProvider):
    """DEVELOPMENT/TEST ONLY in-memory authentication provider."""

    def __init__(
        self,
        users: Iterable[UserSeed],
        *,
        policy: SessionPolicy | None = None,
        store: SessionStore | None = None,
        audit: SecurityAuditLogger | None = None,
        clock=None,
    ) -> None:
        self.policy = policy or SessionPolicy()
        self.store = store or InMemorySessionStore()
        self.audit = audit or SecurityAuditLogger()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._factory = SessionFactory(self.policy, clock=self.clock)
        self._users: dict[str, _UserRecord] = {}
        self._by_username: dict[str, str] = {}
        self._lock = threading.RLock()
        for seed in users:
            self.add_user(seed)

    # ------------------------------------------------------------------
    # User administration (demo only)
    # ------------------------------------------------------------------

    def add_user(self, seed: UserSeed) -> None:
        if not seed.user_id or not seed.username:
            raise ValueError("user_id and username are required")
        username_key = seed.username.strip().lower()
        if not username_key:
            raise ValueError("username is required")
        password_record = hash_password(
            seed.password, iterations=self.policy.password_iterations
        )
        with self._lock:
            if seed.user_id in self._users or username_key in self._by_username:
                raise ValueError("duplicate user_id or username")
            self._users[seed.user_id] = _UserRecord(
                user_id=seed.user_id,
                username=seed.username,
                password=password_record,
                roles=tuple(seed.roles),
                status=seed.status,
                auth_level=seed.auth_level,
            )
            self._by_username[username_key] = seed.user_id

    def update_roles(
        self, user_id: str, roles: tuple[str, ...], *, revoke_sessions: bool = False
    ) -> bool:
        with self._lock:
            record = self._users.get(user_id)
            if record is None:
                return False
            record.roles = tuple(roles)
            record.permission_version += 1
        if revoke_sessions:
            self.revoke_user_sessions(user_id)
        return True

    def set_status(self, user_id: str, status: str) -> bool:
        with self._lock:
            record = self._users.get(user_id)
            if record is None:
                return False
            record.status = status
        if status != "active":
            self.revoke_user_sessions(user_id)
        return True

    def user_roles(self, user_id: str) -> tuple[str, ...] | None:
        with self._lock:
            record = self._users.get(user_id)
            return record.roles if record else None

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def authenticate(
        self,
        credentials: Credentials,
        *,
        device_id: str | None = None,
        transport: str = "bearer",
    ) -> LoginResult:
        trace_id = new_security_id("TRACE")
        if not isinstance(credentials, Credentials):
            return self._login_failure(
                ReasonCode.AUTH_INVALID_CREDENTIALS, trace_id
            )
        username = (credentials.username or "").strip().lower()
        password = credentials.password or ""
        if not username or not password:
            return self._login_failure(
                ReasonCode.AUTH_INVALID_CREDENTIALS, trace_id
            )

        with self._lock:
            user_id = self._by_username.get(username)
            record = self._users.get(user_id) if user_id else None
            if record is None:
                # Do comparable work so a missing username is not obviously
                # faster than a wrong password.
                dummy_verify(
                    password, iterations=self.policy.password_iterations
                )
                self.audit.try_log(
                    "AUTH_FAILED",
                    category=SecurityCategory.AUTHENTICATION.value,
                    outcome="BLOCK",
                    reason_code=ReasonCode.AUTH_INVALID_CREDENTIALS,
                    source="auth",
                    details={"reason": "unknown_or_invalid_credentials"},
                )
                return self._login_failure(
                    ReasonCode.AUTH_INVALID_CREDENTIALS, trace_id
                )

            now = ensure_aware(self.clock())
            locked_until = (
                parse_iso(record.locked_until) if record.locked_until else None
            )
            if locked_until and now < locked_until:
                self.audit.try_log(
                    "AUTH_FAILED",
                    category=SecurityCategory.AUTHENTICATION.value,
                    outcome="BLOCK",
                    reason_code=ReasonCode.AUTH_ACCOUNT_LOCKED,
                    source="auth",
                    details={"user_id": record.user_id, "reason": "locked"},
                )
                return self._login_failure(
                    ReasonCode.AUTH_ACCOUNT_LOCKED, trace_id
                )
            if locked_until and now >= locked_until:
                record.locked_until = None
                record.failed_attempts = 0

            if record.status != "active":
                dummy_verify(
                    password, iterations=self.policy.password_iterations
                )
                self.audit.try_log(
                    "AUTH_FAILED",
                    category=SecurityCategory.AUTHENTICATION.value,
                    outcome="BLOCK",
                    reason_code=ReasonCode.AUTH_ACCOUNT_DISABLED,
                    source="auth",
                    details={
                        "user_id": record.user_id,
                        "reason": "account_status",
                    },
                )
                return self._login_failure(
                    ReasonCode.AUTH_ACCOUNT_DISABLED, trace_id
                )

            if not verify_password(password, record.password):
                record.failed_attempts += 1
                if record.failed_attempts >= self.policy.lockout_threshold:
                    record.locked_until = iso(
                        now
                        + timedelta(seconds=self.policy.lockout_seconds)
                    )
                self.audit.try_log(
                    "AUTH_FAILED",
                    category=SecurityCategory.AUTHENTICATION.value,
                    outcome="BLOCK",
                    reason_code=ReasonCode.AUTH_INVALID_CREDENTIALS,
                    source="auth",
                    details={
                        "user_id": record.user_id,
                        "failed_attempts": record.failed_attempts,
                    },
                )
                return self._login_failure(
                    ReasonCode.AUTH_INVALID_CREDENTIALS, trace_id
                )

            record.failed_attempts = 0
            record.locked_until = None
            roles = record.roles
            permission_version = record.permission_version

        self._enforce_session_cap(record.user_id)

        session_record, token, csrf_token = self._factory.create(
            user_id=record.user_id,
            roles=roles,
            auth_level=record.auth_level,
            permission_version=permission_version,
            transport=transport,
            device_id=device_id,
        )
        self.store.create(session_record)

        principal = Principal(
            user_id=record.user_id,
            roles=roles,
            permissions=permissions_for_roles(roles),
            auth_level=record.auth_level,
            session_id=session_record.session_id,
            account_status="active",
            permission_version=permission_version,
            device_id=device_id,
        )
        session = AuthSession(
            principal=principal,
            session_id=session_record.session_id,
            issued_at=session_record.created_at,
            idle_expires_at=session_record.idle_expires_at,
            absolute_expires_at=session_record.absolute_expires_at,
            transport=transport,
            device_id=device_id,
        )
        decision = SecurityDecision.allow(
            SecurityCategory.AUTHENTICATION.value,
            "AUTHENTICATED",
            message="登录成功。",
            trace_id=trace_id,
            details={
                "session_id": session_record.session_id,
                "auth_level": record.auth_level,
                "roles": list(roles),
            },
        )
        try:
            self.audit.log(
                "AUTH_LOGIN_SUCCEEDED",
                decision=decision,
                principal=principal,
                source="auth",
            )
        except AuditUnavailableError:
            # Do not issue an unaudited authenticated session.
            self.store.revoke(session_record.session_id)
            return LoginResult(
                ok=False,
                decision=fail_closed(
                    details={"component": "security_audit"},
                    trace_id=trace_id,
                ),
            )
        return LoginResult(
            ok=True,
            decision=decision,
            session=session,
            token=token,
            csrf_token=csrf_token,
        )

    # ------------------------------------------------------------------
    # Session validation / logout
    # ------------------------------------------------------------------

    def validate_session(
        self,
        token: str,
        *,
        require_csrf: str | None = None,
    ) -> SessionValidation:
        trace_id = new_security_id("TRACE")
        if not token or not isinstance(token, str):
            return self._session_failure(
                ReasonCode.AUTH_REQUIRED, trace_id, "session token missing"
            )

        record = self.store.get_by_token_hash(hash_token(token))
        if record is None:
            return self._session_failure(
                ReasonCode.AUTH_SESSION_INVALID, trace_id, "unknown session"
            )
        if record.is_revoked():
            return self._session_failure(
                ReasonCode.AUTH_SESSION_REVOKED, trace_id, "session revoked"
            )

        now = ensure_aware(self.clock())
        expired, reason = record.is_expired(now)
        if expired:
            self.store.revoke(record.session_id, at=iso(now))
            return self._session_failure(
                ReasonCode.AUTH_SESSION_EXPIRED,
                trace_id,
                f"session expired ({reason})",
            )

        if record.transport == "cookie":
            if require_csrf is None or not verify_csrf(record, require_csrf):
                return self._session_failure(
                    ReasonCode.AUTH_CSRF_INVALID,
                    trace_id,
                    "csrf validation failed",
                )

        with self._lock:
            user = self._users.get(record.user_id)
        if user is None or user.status != "active":
            self.store.revoke(record.session_id, at=iso(now))
            return self._session_failure(
                ReasonCode.AUTH_ACCOUNT_DISABLED,
                trace_id,
                "account not active",
            )

        refreshed = self._factory.touch(record)
        if refreshed.permission_version != user.permission_version:
            from dataclasses import replace

            refreshed = replace(
                refreshed, permission_version=user.permission_version
            )
        self.store.update(refreshed)

        principal = Principal(
            user_id=user.user_id,
            roles=user.roles,
            permissions=permissions_for_roles(user.roles),
            auth_level=user.auth_level,
            session_id=record.session_id,
            account_status=user.status,
            permission_version=user.permission_version,
            device_id=record.device_id,
        )
        session = AuthSession(
            principal=principal,
            session_id=record.session_id,
            issued_at=record.created_at,
            idle_expires_at=refreshed.idle_expires_at,
            absolute_expires_at=record.absolute_expires_at,
            transport=record.transport,
            device_id=record.device_id,
        )
        decision = SecurityDecision.allow(
            SecurityCategory.AUTHENTICATION.value,
            "SESSION_VALID",
            message="会话有效。",
            trace_id=trace_id,
            details={"session_id": record.session_id},
        )
        return SessionValidation(ok=True, decision=decision, session=session)

    def logout(self, token: str) -> SecurityDecision:
        trace_id = new_security_id("TRACE")
        record = (
            self.store.get_by_token_hash(hash_token(token))
            if token and isinstance(token, str)
            else None
        )
        if record is None:
            # Idempotent logout; do not reveal whether a token existed.
            return SecurityDecision.allow(
                SecurityCategory.AUTHENTICATION.value,
                ReasonCode.AUTH_SESSION_INVALID,
                message="已退出登录。",
                trace_id=trace_id,
            )
        self.store.revoke(record.session_id)
        decision = SecurityDecision.allow(
            SecurityCategory.AUTHENTICATION.value,
            "SESSION_REVOKED",
            message="已退出登录。",
            trace_id=trace_id,
            details={"session_id": record.session_id},
        )
        self.audit.try_log(
            "AUTH_LOGOUT",
            decision=decision,
            session_id=record.session_id,
            source="auth",
            details={"user_id": record.user_id},
        )
        return decision

    def revoke_user_sessions(self, user_id: str) -> int:
        return self.store.revoke_user(user_id)

    def current_principal(self, token: str) -> Principal | None:
        result = self.validate_session(token)
        return result.principal if result.ok else None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _enforce_session_cap(self, user_id: str) -> None:
        active = self.store.active_for_user(user_id)
        if len(active) < self.policy.max_sessions_per_user:
            return
        ordered = sorted(active, key=lambda record: record.created_at)
        excess = len(active) - self.policy.max_sessions_per_user + 1
        for record in ordered[:excess]:
            self.store.revoke(record.session_id)

    def _login_failure(self, reason_code: str, trace_id: str) -> LoginResult:
        decision = SecurityDecision.block(
            SecurityCategory.AUTHENTICATION.value,
            reason_code,
            message="认证失败，请检查凭据或账户状态。",
            trace_id=trace_id,
            retryable=(reason_code != ReasonCode.AUTH_ACCOUNT_DISABLED),
        )
        return LoginResult(ok=False, decision=decision)

    def _session_failure(
        self, reason_code: str, trace_id: str, detail: str
    ) -> SessionValidation:
        decision = SecurityDecision.block(
            SecurityCategory.AUTHENTICATION.value,
            reason_code,
            message="会话无效或已过期，请重新登录。",
            trace_id=trace_id,
            details={"reason": detail},
        )
        self.audit.try_log(
            "SESSION_REJECTED",
            category=SecurityCategory.AUTHENTICATION.value,
            outcome="BLOCK",
            reason_code=reason_code,
            source="auth",
            details={"reason": detail},
        )
        return SessionValidation(ok=False, decision=decision)
