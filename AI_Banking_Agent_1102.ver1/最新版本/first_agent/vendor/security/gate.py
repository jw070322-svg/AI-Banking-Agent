"""A deny-by-default prototype gate. It never executes tools."""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    # Populate only from verified server-side identity and ownership lookups.
    user_id: str
    scopes: frozenset[str]
    resources: frozenset[str]

    def __post_init__(self):
        if not isinstance(self.user_id, str) or not self.user_id.strip():
            raise ValueError("An authenticated principal ID is required")
        for collection in (self.scopes, self.resources):
            if not isinstance(collection, frozenset) or any(
                    not isinstance(v, str) or not v.strip() for v in collection):
                raise ValueError("Scopes and resources must be frozensets of identifiers")


@dataclass(frozen=True)
class ToolPolicy:
    required_scope: str
    effect: str  # Only read/write; unknown effect must never become read.

    def __post_init__(self):
        if (not isinstance(self.required_scope, str) or not self.required_scope.strip()
                or self.effect not in {"read", "write"}):
            raise ValueError("Tool policy needs a nonblank scope and read/write effect")


@dataclass(frozen=True)
class GateDecision:
    decision: str
    reason: str
    policy_version: str


class SecurityGate:
    def __init__(self, tools: Mapping[str, ToolPolicy], policy_version: str):
        if not isinstance(policy_version, str) or not policy_version.strip():
            raise ValueError("A policy version is required")
        if any(not isinstance(k, str) or not k.strip() or not isinstance(v, ToolPolicy)
               for k, v in tools.items()):
            raise ValueError("Tools must map identifiers to ToolPolicy objects")
        self._tools = dict(tools)
        self.policy_version = policy_version

    def check(self, principal: Principal | None, tool: str, resource_id: str) -> GateDecision:
        def result(decision, reason):
            return GateDecision(decision, reason, self.policy_version)
        if not isinstance(principal, Principal):
            return result("block", "authenticated_principal_required")
        if not isinstance(tool, str) or tool not in self._tools:
            return result("block", "tool_not_allowlisted")
        policy = self._tools[tool]
        if policy.required_scope not in principal.scopes:
            return result("block", "missing_scope")
        if not isinstance(resource_id, str) or resource_id not in principal.resources:
            return result("block", "resource_not_authorized")
        if policy.effect == "write":
            # TODO: Add server-side parameter schemas, bound expiring confirmation,
            # revalidation, idempotency and receipt handling before enabling writes.
            return result("review", "write_execution_and_confirmation_not_implemented")
        return result("pass", "configured_read_scope_and_resource_verified")
