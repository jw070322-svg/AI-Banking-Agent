"""Role-based and resource-level authorization for Module 8.

Authorization is always evaluated server-side from a `Principal` produced by
authentication. Roles, permissions, account IDs, user IDs and ownership claims
supplied by the LLM or an untrusted request are never accepted as facts.

The model is deliberately progressive: reading an account does not imply
analysing it, creating a plan, initiating a transaction, or executing one.
`transaction:initiate` and `transaction:execute` are separate permissions.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .models import (
    Principal,
    ReasonCode,
    ResolvedResource,
    ResourceRef,
    SecurityCategory,
    SecurityDecision,
    new_security_id,
)
from .sessions import ensure_aware, parse_iso

# ----------------------------------------------------------------------
# Permissions
# ----------------------------------------------------------------------


class Permission:
    # Module 6-compatible strings. Keeping the same names lets the security
    # gateway hand a least-privilege permission set to ToolCallContext without
    # maintaining a second, divergent vocabulary.
    ACCOUNT_READ = "account:read"
    TRANSACTIONS_READ = "transactions:read"
    ANALYSIS_READ = "analysis:read"
    PRODUCTS_READ = "products:read"
    POLICY_READ = "policy:read"
    PLANNING_WRITE = "planning:write"
    TRANSFER_WRITE = "transfer:write"
    CARD_READ = "card:read"
    CARD_WRITE = "card:write"
    LOAN_READ = "loan:read"
    AUDIT_WRITE = "audit:write"

    # Module 8 additions for progressive authorization.
    RECOMMENDATIONS_GENERATE = "recommendations:generate"
    TRANSACTION_INITIATE = "transaction:initiate"
    TRANSACTION_EXECUTE = "transaction:execute"
    ADMIN_ACCESS = "admin:access"
    USER_MANAGE = "user:manage"
    AUDIT_READ = "audit:read"


ALL_PERMISSIONS = frozenset(
    {
        Permission.ACCOUNT_READ,
        Permission.TRANSACTIONS_READ,
        Permission.ANALYSIS_READ,
        Permission.PRODUCTS_READ,
        Permission.POLICY_READ,
        Permission.PLANNING_WRITE,
        Permission.TRANSFER_WRITE,
        Permission.CARD_READ,
        Permission.CARD_WRITE,
        Permission.LOAN_READ,
        Permission.AUDIT_WRITE,
        Permission.RECOMMENDATIONS_GENERATE,
        Permission.TRANSACTION_INITIATE,
        Permission.TRANSACTION_EXECUTE,
        Permission.ADMIN_ACCESS,
        Permission.USER_MANAGE,
        Permission.AUDIT_READ,
    }
)

# Illustrative roles, adapted to this prototype. Administrators do NOT receive
# customer financial permissions by default; access requires an explicit,
# time-bound break-glass grant that is flagged for review.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "customer": frozenset(
        {
            Permission.ACCOUNT_READ,
            Permission.TRANSACTIONS_READ,
            Permission.ANALYSIS_READ,
            Permission.PRODUCTS_READ,
            Permission.POLICY_READ,
            Permission.PLANNING_WRITE,
            Permission.TRANSFER_WRITE,
            Permission.CARD_READ,
            Permission.CARD_WRITE,
            Permission.LOAN_READ,
            Permission.RECOMMENDATIONS_GENERATE,
            Permission.TRANSACTION_INITIATE,
            Permission.TRANSACTION_EXECUTE,
        }
    ),
    # Financial advisors can read/analyse/recommend for explicitly assigned
    # clients. They cannot initiate or execute a transfer.
    "advisor": frozenset(
        {
            Permission.ACCOUNT_READ,
            Permission.TRANSACTIONS_READ,
            Permission.ANALYSIS_READ,
            Permission.PRODUCTS_READ,
            Permission.POLICY_READ,
            Permission.PLANNING_WRITE,
            Permission.CARD_READ,
            Permission.LOAN_READ,
            Permission.RECOMMENDATIONS_GENERATE,
        }
    ),
    "admin": frozenset(
        {
            Permission.ADMIN_ACCESS,
            Permission.USER_MANAGE,
            Permission.AUDIT_READ,
            Permission.POLICY_READ,
        }
    ),
    "auditor": frozenset(
        {
            Permission.AUDIT_READ,
            Permission.POLICY_READ,
        }
    ),
    # Example least-privilege role: can start a transaction but cannot execute
    # it. Useful for separating front-office initiation from approval.
    "initiator": frozenset(
        {
            Permission.ACCOUNT_READ,
            Permission.TRANSACTIONS_READ,
            Permission.TRANSACTION_INITIATE,
        }
    ),
}

READ_ONLY_PERMISSIONS = frozenset(
    {
        Permission.ACCOUNT_READ,
        Permission.TRANSACTIONS_READ,
        Permission.ANALYSIS_READ,
        Permission.PRODUCTS_READ,
        Permission.POLICY_READ,
        Permission.CARD_READ,
        Permission.LOAN_READ,
    }
)


def permissions_for_roles(roles: Iterable[str]) -> frozenset[str]:
    result: set[str] = set()
    for role in roles:
        result.update(ROLE_PERMISSIONS.get(str(role), frozenset()))
    return frozenset(result)


# ----------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    permission: str
    resource_type: str | None
    mutating: bool
    sensitivity: str  # low / medium / high / critical
    description: str = ""


ACTIONS: dict[str, ActionDefinition] = {
    "account.read": ActionDefinition(
        "account.read", Permission.ACCOUNT_READ, "account", False, "medium"
    ),
    "transaction.read": ActionDefinition(
        "transaction.read",
        Permission.TRANSACTIONS_READ,
        "account",
        False,
        "high",
    ),
    "analysis.execute": ActionDefinition(
        "analysis.execute", Permission.ANALYSIS_READ, "account", False, "medium"
    ),
    "recommendation.generate": ActionDefinition(
        "recommendation.generate",
        Permission.RECOMMENDATIONS_GENERATE,
        "account",
        False,
        "medium",
    ),
    "plan.create": ActionDefinition(
        "plan.create", Permission.PLANNING_WRITE, None, True, "medium"
    ),
    "plan.update": ActionDefinition(
        "plan.update", Permission.PLANNING_WRITE, "plan", True, "high"
    ),
    "alert.create": ActionDefinition(
        "alert.create", Permission.PLANNING_WRITE, "account", True, "medium"
    ),
    "alert.update": ActionDefinition(
        "alert.update", Permission.PLANNING_WRITE, "alert", True, "medium"
    ),
    "product.search": ActionDefinition(
        "product.search", Permission.PRODUCTS_READ, None, False, "low"
    ),
    "product.compare": ActionDefinition(
        "product.compare", Permission.PRODUCTS_READ, None, False, "low"
    ),
    "policy.retrieve": ActionDefinition(
        "policy.retrieve", Permission.POLICY_READ, None, False, "low"
    ),
    "loan.calculate": ActionDefinition(
        "loan.calculate", Permission.ANALYSIS_READ, None, False, "medium"
    ),
    "portfolio.calculate": ActionDefinition(
        "portfolio.calculate", Permission.ANALYSIS_READ, None, False, "medium"
    ),
    "transaction.initiate": ActionDefinition(
        "transaction.initiate",
        Permission.TRANSACTION_INITIATE,
        "account",
        True,
        "critical",
    ),
    "transaction.execute": ActionDefinition(
        "transaction.execute",
        Permission.TRANSACTION_EXECUTE,
        "account",
        True,
        "critical",
    ),
    "admin.access": ActionDefinition(
        "admin.access", Permission.ADMIN_ACCESS, None, True, "critical"
    ),
    "audit.read": ActionDefinition(
        "audit.read", Permission.AUDIT_READ, None, False, "high"
    ),
}

# Module 6 tool name -> Module 8 actions. Unknown tools are denied by the
# gateway (allowlist), not passed through to the registry.
TOOL_ACTIONS: dict[str, tuple[str, ...]] = {
    "get_account_balance": ("account.read",),
    "get_transactions": ("transaction.read",),
    "analyze_cashflow": ("analysis.execute",),
    "calculate_financial_health": ("analysis.execute",),
    "calculate_risk": ("analysis.execute",),
    "search_products": ("product.search",),
    "compare_products": ("product.compare",),
    "retrieve_policy": ("policy.retrieve",),
    "calculate_loan": ("loan.calculate",),
    "calculate_portfolio": ("portfolio.calculate",),
    "create_budget": ("plan.create",),
    "create_alert": ("alert.create",),
    # Initiate is checked at planning/prepare; execute is additionally checked
    # immediately before dispatch.
    "execute_transaction": ("transaction.initiate", "transaction.execute"),
}

CRITICAL_AUTH_LEVELS = frozenset({"strong", "step_up"})


def actions_for_tool(tool_name: str, *, phase: str = "execute") -> tuple[str, ...]:
    actions = TOOL_ACTIONS.get(tool_name)
    if not actions:
        return ()
    if tool_name == "execute_transaction" and phase == "plan":
        return (actions[0],)
    return actions


# ----------------------------------------------------------------------
# Grants
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class AccessGrant:
    """Explicit, server-stored grant for shared/advisor/break-glass access.

    A grant is never created from an LLM request. In production it is created
    by an entitlement workflow with maker/checker approval.
    """

    grant_id: str
    grantee_id: str
    owner_id: str
    permissions: frozenset[str]
    resource_type: str = "account"
    resource_id: str | None = None
    purpose: str = ""
    granted_by: str = ""
    expires_at: str | None = None
    break_glass: bool = False
    active: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.permissions, (list, set, tuple)):
            object.__setattr__(self, "permissions", frozenset(self.permissions))

    def is_active(self, now: datetime) -> bool:
        if not self.active:
            return False
        if self.expires_at is None:
            return True
        try:
            return ensure_aware(parse_iso(self.expires_at)) > now
        except ValueError:
            return False

    def allows(self, permission: str, resource: ResourceRef | None) -> bool:
        if not self.is_active(datetime.now(timezone.utc)):
            return False
        if "*" not in self.permissions and permission not in self.permissions:
            return False
        if self.resource_type != "*" and resource is not None:
            if self.resource_type != resource.type:
                return False
        if (
            self.resource_id
            and resource is not None
            and resource.id
            and self.resource_id != resource.id
        ):
            return False
        return True


class InMemoryAccessGrantStore:
    def __init__(self, *, clock=None) -> None:
        self._grants: dict[str, AccessGrant] = {}
        self._lock = threading.RLock()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def add(self, grant: AccessGrant) -> None:
        with self._lock:
            self._grants[grant.grant_id] = grant

    def revoke(self, grant_id: str) -> bool:
        with self._lock:
            grant = self._grants.get(grant_id)
            if grant is None:
                return False
            self._grants[grant_id] = AccessGrant(
                grant_id=grant.grant_id,
                grantee_id=grant.grantee_id,
                owner_id=grant.owner_id,
                permissions=grant.permissions,
                resource_type=grant.resource_type,
                resource_id=grant.resource_id,
                purpose=grant.purpose,
                granted_by=grant.granted_by,
                expires_at=grant.expires_at,
                break_glass=grant.break_glass,
                active=False,
            )
            return True

    def active_grants(self, grantee_id: str) -> list[AccessGrant]:
        now = ensure_aware(self._clock())
        with self._lock:
            return [
                grant
                for grant in self._grants.values()
                if grant.grantee_id == grantee_id and grant.is_active(now)
            ]

    def active_owner_ids(self, grantee_id: str) -> set[str]:
        return {grant.owner_id for grant in self.active_grants(grantee_id)}

    def find_for(
        self,
        grantee_id: str,
        owner_id: str,
        permission: str,
        resource: ResourceRef | None,
    ) -> AccessGrant | None:
        for grant in self.active_grants(grantee_id):
            if grant.owner_id != owner_id:
                continue
            if grant.allows(permission, resource):
                return grant
        return None


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------


class AuthorizationService:
    """Server-side permission + ownership checks.

    `resource_resolver` must implement `resolve(resource, owner_candidates)` and
    return a `ResolvedResource | None`. The gateway never trusts a resource ID
    without this resolution.
    """

    def __init__(
        self,
        resolver: Any,
        *,
        grants: InMemoryAccessGrantStore | None = None,
        policy_version: str | None = None,
    ) -> None:
        self.resolver = resolver
        self.grants = grants or InMemoryAccessGrantStore()
        self.policy_version = policy_version

    def authorize(
        self,
        principal: Principal,
        action: str,
        resource: ResourceRef | None = None,
        *,
        allow_unscoped: bool = False,
        expected_permission_version: int | None = None,
        trace_id: str | None = None,
    ) -> SecurityDecision:
        spec = ACTIONS.get(action)
        if spec is None:
            return SecurityDecision.block(
                SecurityCategory.AUTHORIZATION.value,
                ReasonCode.UNKNOWN_ACTION,
                details={"action": action},
                trace_id=trace_id,
            )

        if (
            expected_permission_version is not None
            and expected_permission_version != principal.permission_version
        ):
            return SecurityDecision.block(
                SecurityCategory.AUTHORIZATION.value,
                ReasonCode.PERMISSION_CHANGED,
                details={
                    "action": action,
                    "expected_permission_version": expected_permission_version,
                    "current_permission_version": principal.permission_version,
                },
                trace_id=trace_id,
            )

        if principal.account_status != "active":
            return SecurityDecision.block(
                SecurityCategory.AUTHORIZATION.value,
                ReasonCode.AUTH_ACCOUNT_DISABLED,
                details={"account_status": principal.account_status},
                trace_id=trace_id,
            )

        if not principal.has(spec.permission):
            # Administrators do not receive customer financial permissions by
            # default. An explicit, time-bound break-glass grant is the only
            # path, and it is flagged for review.
            if (
                spec.resource_type
                and resource is not None
                and (resource.id or "").strip()
                and "admin" in principal.roles
                and principal.has(Permission.ADMIN_ACCESS)
            ):
                resolved = self._resolve(principal, resource)
                if resolved is not None:
                    grant = self.grants.find_for(
                        principal.user_id,
                        resolved.owner_id,
                        spec.permission,
                        resource,
                    )
                    if grant is not None and grant.break_glass:
                        return SecurityDecision.allow(
                            SecurityCategory.AUTHORIZATION.value,
                            "GRANTED_RESOURCE_ACCESS",
                            details={
                                "action": action,
                                "resource_type": resolved.type,
                                "access_basis": "break_glass",
                                "grant_id": grant.grant_id,
                                "purpose": grant.purpose,
                                "permission_version": principal.permission_version,
                            },
                            trace_id=trace_id,
                            requires_review=True,
                        )
            return SecurityDecision.block(
                SecurityCategory.AUTHORIZATION.value,
                ReasonCode.INSUFFICIENT_PERMISSION,
                details={"action": action, "required_permission": spec.permission},
                trace_id=trace_id,
            )

        if (
            spec.sensitivity == "critical"
            and principal.auth_level not in CRITICAL_AUTH_LEVELS
        ):
            return SecurityDecision.block(
                SecurityCategory.AUTHORIZATION.value,
                ReasonCode.AUTH_INSUFFICIENT_LEVEL,
                details={"action": action, "auth_level": principal.auth_level},
                trace_id=trace_id,
            )

        if spec.resource_type:
            if resource is None or not (resource.id or "").strip():
                if allow_unscoped:
                    return SecurityDecision.allow(
                        SecurityCategory.AUTHORIZATION.value,
                        "OWNED_SCOPE_ALLOWED",
                        details={
                            "action": action,
                            "scope": "all_owned_resources",
                            "permission_version": principal.permission_version,
                        },
                        trace_id=trace_id,
                    )
                return SecurityDecision.block(
                    SecurityCategory.AUTHORIZATION.value,
                    ReasonCode.RESOURCE_REQUIRED,
                    details={"action": action, "resource_type": spec.resource_type},
                    trace_id=trace_id,
                )

            resolved = self._resolve(principal, resource)
            if resolved is None:
                # Deliberately indistinguishable from a resource that exists
                # but belongs to someone else. This prevents IDOR probing.
                return SecurityDecision.block(
                    SecurityCategory.AUTHORIZATION.value,
                    ReasonCode.RESOURCE_NOT_FOUND,
                    details={
                        "action": action,
                        "resource_type": resource.type,
                    },
                    trace_id=trace_id,
                )

            if resolved.owner_id == principal.user_id:
                return SecurityDecision.allow(
                    SecurityCategory.AUTHORIZATION.value,
                    "RESOURCE_OWNER_ALLOWED",
                    details={
                        "action": action,
                        "resource_type": resolved.type,
                        "access_basis": "owner",
                        "permission_version": principal.permission_version,
                    },
                    trace_id=trace_id,
                )

            grant = self.grants.find_for(
                principal.user_id,
                resolved.owner_id,
                spec.permission,
                resource,
            )
            if grant is not None:
                if grant.break_glass and (
                    "admin" not in principal.roles
                    or not principal.has(Permission.ADMIN_ACCESS)
                ):
                    grant = None
                else:
                    return SecurityDecision.allow(
                        SecurityCategory.AUTHORIZATION.value,
                        "GRANTED_RESOURCE_ACCESS",
                        details={
                            "action": action,
                            "resource_type": resolved.type,
                            "access_basis": (
                                "break_glass" if grant.break_glass else "grant"
                            ),
                            "grant_id": grant.grant_id,
                            "purpose": grant.purpose,
                            "permission_version": principal.permission_version,
                        },
                        trace_id=trace_id,
                        requires_review=grant.break_glass,
                    )

            return SecurityDecision.block(
                SecurityCategory.AUTHORIZATION.value,
                ReasonCode.RESOURCE_FORBIDDEN,
                details={
                    "action": action,
                    "resource_type": resolved.type,
                    "access_basis": "denied",
                },
                trace_id=trace_id,
                requires_review=(
                    "admin" in principal.roles and grant is None
                ),
            )

        return SecurityDecision.allow(
            SecurityCategory.AUTHORIZATION.value,
            "PERMISSION_ALLOWED",
            details={
                "action": action,
                "permission": spec.permission,
                "permission_version": principal.permission_version,
            },
            trace_id=trace_id,
        )

    def _resolve(
        self, principal: Principal, resource: ResourceRef
    ) -> ResolvedResource | None:
        candidates = {principal.user_id}
        candidates.update(self.grants.active_owner_ids(principal.user_id))
        try:
            return self.resolver.resolve(resource, candidates)
        except Exception:
            # Resolver failure is not authorization. Fail closed.
            return None

    def resolve_resource(
        self, principal: Principal, resource: ResourceRef
    ) -> ResolvedResource | None:
        """Public resolution used by the transaction security policy."""
        return self._resolve(principal, resource)

    def permission_snapshot(self, principal: Principal) -> dict[str, Any]:
        return {
            "user_id": principal.user_id,
            "roles": list(principal.roles),
            "permissions": sorted(principal.permissions),
            "permission_version": principal.permission_version,
        }
