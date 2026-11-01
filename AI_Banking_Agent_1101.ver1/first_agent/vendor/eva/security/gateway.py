"""Security gateways for the Agent Orchestrator and Module 6 Tool Registry.

Two composition points, neither of which modifies the completed modules:

- `SecureAgentGateway` wraps the existing `BankingAgent.handle` call. It
  authenticates a bearer/cookie session, screens the user input, restricts
  scopes when required, and filters the final reply.
- `AuthorizedToolGateway` wraps Module 6's `ToolRegistry.execute`. It resolves
  the trusted principal from a session token, performs resource-level
  authorization, consumes a transaction-bound confirmation, and only then
  dispatches to the unchanged registry. Module 6 still enforces its own
  permissions, confirmation flag, idempotency and Risk/Compliance adapters.

Fail-closed rule: if any mandatory dependency is missing or raises, the
protected operation returns a BLOCK decision and the handler is not called.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ..models import Session
from ..tool_calling.models import ToolCallContext, ToolCallResult
from .audit import AuditUnavailableError, SecurityAuditLogger
from .auth import AuthenticationProvider
from .authorization import (
    ACTIONS,
    READ_ONLY_PERMISSIONS,
    AuthorizationService,
    actions_for_tool,
)
from .confirmation import (
    ConfirmationService,
    TransactionSecurityPolicy,
    canonical_json,
)
from .injection import (
    OutputGuard,
    PromptInjectionGuard,
    ScreeningResult,
    ToolOutputValidation,
)
from .models import (
    Decision,
    Principal,
    ReasonCode,
    ResolvedResource,
    ResourceRef,
    SecurityCategory,
    SecurityDecision,
    fail_closed,
    new_security_id,
)

LEGACY_SCOPES = frozenset(
    {
        "account:read",
        "transactions:read",
        "transfer:write",
        "card:read",
        "card:write",
        "loan:read",
    }
)
READ_ONLY_LEGACY_SCOPES = frozenset(
    {"account:read", "transactions:read", "card:read", "loan:read"}
)
# Tools whose account reference is optional. They operate only on the
# principal's own scope; the registry itself also filters by context.user_id.
OPTIONAL_ACCOUNT_SCOPE_TOOLS = frozenset(
    {
        "get_account_balance",
        "analyze_cashflow",
        "calculate_financial_health",
        "calculate_risk",
        "calculate_loan",
        "calculate_portfolio",
        "create_alert",
    }
)


@dataclass(frozen=True)
class SecureToolResult:
    ok: bool
    decision: SecurityDecision
    tool_result: ToolCallResult | None = None
    safe_data: Mapping[str, Any] | None = None
    output_validation: ToolOutputValidation | None = None
    trace_id: str = ""
    security_event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "decision": self.decision.to_dict(),
            "tool_result": (
                self.tool_result.to_dict(include_evidence=False)
                if self.tool_result is not None
                else None
            ),
            "safe_data": dict(self.safe_data) if self.safe_data else None,
            "output_validation": (
                self.output_validation.to_dict()
                if self.output_validation is not None
                else None
            ),
            "trace_id": self.trace_id,
            "security_event_id": self.security_event_id,
        }


class AuthorizedToolGateway:
    def __init__(
        self,
        registry: Any,
        auth_provider: AuthenticationProvider | None,
        authorization: AuthorizationService | None,
        *,
        injection_guard: PromptInjectionGuard | None = None,
        confirmation: ConfirmationService | None = None,
        output_guard: OutputGuard | None = None,
        audit: SecurityAuditLogger | None = None,
        transaction_policy: TransactionSecurityPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.auth = auth_provider
        self.authorization = authorization
        self.injection_guard = injection_guard
        self.confirmation = confirmation
        self.output_guard = output_guard
        self.audit = audit or SecurityAuditLogger()
        self.transaction_policy = transaction_policy or TransactionSecurityPolicy()

    # ------------------------------------------------------------------
    # Execute a tool
    # ------------------------------------------------------------------

    def execute(
        self,
        session_token: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        request_text: str = "",
        confirmation_id: str | None = None,
        csrf_token: str | None = None,
        expected_permission_version: int | None = None,
    ) -> SecureToolResult:
        trace_id = new_security_id("TRACE")
        try:
            return self._execute_impl(
                session_token,
                tool_name,
                arguments,
                request_text=request_text,
                confirmation_id=confirmation_id,
                csrf_token=csrf_token,
                expected_permission_version=expected_permission_version,
            )
        except Exception as exc:
            # A security-layer failure must never fall through to dispatch.
            return self._result(
                fail_closed(
                    details={
                        "component": "security_layer",
                        "exception_type": type(exc).__name__,
                    },
                    trace_id=trace_id,
                ),
                trace_id,
            )

    def _execute_impl(
        self,
        session_token: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        request_text: str = "",
        confirmation_id: str | None = None,
        csrf_token: str | None = None,
        expected_permission_version: int | None = None,
    ) -> SecureToolResult:
        trace_id = new_security_id("TRACE")
        args = dict(arguments or {})

        definition = self._definition(tool_name)
        if definition is None:
            return self._result(
                SecurityDecision.block(
                    SecurityCategory.AUTHORIZATION.value,
                    ReasonCode.TOOL_NOT_ALLOWED,
                    details={"tool": tool_name},
                    trace_id=trace_id,
                ),
                trace_id,
            )
        mutating = bool(getattr(definition, "mutating", False))
        missing = self._missing_dependencies(mutating)
        if missing:
            return self._result(
                fail_closed(details={"missing": missing}, trace_id=trace_id),
                trace_id,
            )

        assert self.auth is not None
        validation = self.auth.validate_session(
            session_token, require_csrf=csrf_token
        )
        if not validation.ok or validation.principal is None:
            return self._result(validation.decision, trace_id)
        principal = validation.principal

        if (
            expected_permission_version is not None
            and expected_permission_version != principal.permission_version
        ):
            return self._result(
                SecurityDecision.block(
                    SecurityCategory.AUTHORIZATION.value,
                    ReasonCode.PERMISSION_CHANGED,
                    details={
                        "expected_permission_version": expected_permission_version,
                        "current_permission_version": principal.permission_version,
                    },
                    trace_id=trace_id,
                ),
                trace_id,
            )

        screening = self._screen_request(
            principal, request_text, mutating, args
        )
        if screening is not None and not screening.allowed:
            return self._result(screening.decision, trace_id)
        if screening is not None and screening.restricted and mutating:
            return self._result(
                SecurityDecision.block(
                    SecurityCategory.SCREENING.value,
                    ReasonCode.RESTRICTED_CAPABILITY,
                    message="当前请求仅允许只读操作，状态变更已被阻止。",
                    trace_id=trace_id,
                ),
                trace_id,
            )

        authorized, resources, binding = self._authorize_tool(
            principal, tool_name, args, trace_id, phase="execute"
        )
        if authorized is None:
            return self._result(
                SecurityDecision.block(
                    SecurityCategory.AUTHORIZATION.value,
                    ReasonCode.UNKNOWN_ACTION,
                    details={"tool": tool_name},
                    trace_id=trace_id,
                ),
                trace_id,
            )
        if not authorized.allowed:
            return self._result(authorized, trace_id)
        if authorized.requires_review and mutating:
            return self._result(
                SecurityDecision.review(
                    SecurityCategory.AUTHORIZATION.value,
                    ReasonCode.REVIEW_REQUIRED,
                    message="该操作需要人工复核后才能执行。",
                    trace_id=trace_id,
                    details={"tool": tool_name, "access_basis": "break_glass"},
                ),
                trace_id,
            )
        review_required = bool(authorized.requires_review)

        idempotency_key: str | None = None
        confirmation_action: str | None = None
        confirmation_resource: str | None = None
        if mutating:
            assert self.confirmation is not None
            if not confirmation_id:
                return self._result(
                    SecurityDecision.block(
                        SecurityCategory.CONFIRMATION.value,
                        ReasonCode.CONFIRMATION_REQUIRED,
                        message="该操作需要绑定具体交易内容的一次性确认。",
                        details={"tool": tool_name},
                        trace_id=trace_id,
                    ),
                    trace_id,
                )
            confirmation_action, confirmation_resource, parameters = (
                self._confirmation_binding(
                    principal, tool_name, args, resources, binding, trace_id
                )
            )
            if confirmation_action is None:
                return self._result(
                    SecurityDecision.block(
                        SecurityCategory.CONFIRMATION.value,
                        ReasonCode.CONFIRMATION_INVALID,
                        details={"tool": tool_name},
                        trace_id=trace_id,
                    ),
                    trace_id,
                )
            consumption = self.confirmation.consume(
                principal,
                confirmation_id,
                action=confirmation_action,
                resource_id=confirmation_resource,
                parameters=parameters,
            )
            if not consumption.ok:
                return self._result(consumption.decision, trace_id)
            idempotency_key = consumption.idempotency_key

        # Audit the authorization decision before dispatch. For mutations this
        # audit is mandatory: no audit, no state change.
        audit_decision = SecurityDecision.allow(
            SecurityCategory.AUTHORIZATION.value,
            "TOOL_EXECUTION_AUTHORIZED",
            message="工具调用已通过安全检查。",
            trace_id=trace_id,
            details={
                "tool": tool_name,
                "mutating": mutating,
                "confirmation_action": confirmation_action,
            },
        )
        try:
            event = self.audit.log(
                "TOOL_EXECUTION_AUTHORIZED",
                decision=audit_decision,
                principal=principal,
                source="tool_gateway",
                details={
                    "tool": tool_name,
                    "mutating": mutating,
                    "confirmation_action": confirmation_action,
                },
            )
        except AuditUnavailableError:
            return self._result(
                fail_closed(
                    reason_code=ReasonCode.SECURITY_AUDIT_UNAVAILABLE,
                    details={"component": "security_audit"},
                    trace_id=trace_id,
                ),
                trace_id,
            )

        permissions = principal.permissions
        if screening is not None and screening.restricted:
            permissions = frozenset(permissions) & READ_ONLY_PERMISSIONS
        context = ToolCallContext(
            user_id=principal.user_id,
            session_id=principal.session_id,
            permissions=permissions,
            request_text=request_text,
            auth_level=principal.auth_level,
            confirmed=mutating,
            confirmation_id=confirmation_id if mutating else None,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )

        try:
            tool_result = self.registry.execute(tool_name, args, context)
        except Exception:
            return self._result(
                SecurityDecision.block(
                    SecurityCategory.AUTHORIZATION.value,
                    ReasonCode.TOOL_EXECUTION_FAILED,
                    message="工具执行失败，操作未完成。",
                    trace_id=trace_id,
                    details={"tool": tool_name},
                ),
                trace_id,
                event_id=event.event_id,
            )

        if not tool_result.ok:
            error_code = (
                tool_result.error.code if tool_result.error else "UNKNOWN"
            )
            decision = SecurityDecision.block(
                SecurityCategory.AUTHORIZATION.value,
                ReasonCode.TOOL_EXECUTION_DENIED,
                message="工具层拒绝了该调用。",
                trace_id=trace_id,
                details={
                    "tool": tool_name,
                    "tool_error_code": error_code,
                    "tool_status": tool_result.status,
                },
                requires_review=(error_code == "MUTATION_OUTCOME_UNKNOWN"),
            )
            audit_event = self._try_audit(
                "TOOL_EXECUTION_DENIED",
                decision,
                principal,
                {"tool": tool_name, "tool_error_code": error_code},
            )
            return self._result(
                decision,
                trace_id,
                tool_result=tool_result,
                event_id=audit_event,
            )

        assert self.output_guard is not None
        output = self.output_guard.sanitize_tool_output(
            tool_name, tool_result.data, principal, trace_id=trace_id
        )
        if not output.allowed:
            audit_event = self._try_audit(
                "TOOL_OUTPUT_BLOCKED",
                output.decision,
                principal,
                {"tool": tool_name},
            )
            return self._result(
                output.decision,
                trace_id,
                tool_result=tool_result,
                output_validation=output,
                event_id=audit_event,
            )

        success = SecurityDecision.allow(
            SecurityCategory.AUTHORIZATION.value,
            "TOOL_EXECUTION_SUCCEEDED",
            message="工具调用完成并通过安全检查。",
            trace_id=trace_id,
            details={
                "tool": tool_name,
                "output_redacted": output.redacted,
                "output_review": output.requires_review,
            },
            requires_review=output.requires_review or review_required,
        )
        try:
            final_event = self.audit.log(
                "TOOL_EXECUTION_SUCCEEDED",
                decision=success,
                principal=principal,
                source="tool_gateway",
                details={
                    "tool": tool_name,
                    "mutating": mutating,
                    "output_redacted": output.redacted,
                },
            )
        except AuditUnavailableError:
            # The mutation may already have happened. Never report success
            # without an audit record; mark it for review instead.
            return self._result(
                fail_closed(
                    reason_code=ReasonCode.SECURITY_AUDIT_UNAVAILABLE,
                    details={
                        "component": "security_audit",
                        "mutation_executed": mutating,
                    },
                    trace_id=trace_id,
                ),
                trace_id,
                tool_result=tool_result,
                output_validation=output,
                event_id=event.event_id,
            )

        return self._result(
            success,
            trace_id,
            tool_result=tool_result,
            output_validation=output,
            event_id=final_event.event_id,
        )

    # ------------------------------------------------------------------
    # Plan-time check (no dispatch)
    # ------------------------------------------------------------------

    def check(
        self,
        session_token: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        request_text: str = "",
        csrf_token: str | None = None,
    ) -> SecurityDecision:
        trace_id = new_security_id("TRACE")
        try:
            return self._check_impl(
                session_token,
                tool_name,
                arguments,
                request_text=request_text,
                csrf_token=csrf_token,
            )
        except Exception as exc:
            return fail_closed(
                details={
                    "component": "security_layer",
                    "exception_type": type(exc).__name__,
                },
                trace_id=trace_id,
            )

    def _check_impl(
        self,
        session_token: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        request_text: str = "",
        csrf_token: str | None = None,
    ) -> SecurityDecision:
        trace_id = new_security_id("TRACE")
        definition = self._definition(tool_name)
        if definition is None:
            return SecurityDecision.block(
                SecurityCategory.AUTHORIZATION.value,
                ReasonCode.TOOL_NOT_ALLOWED,
                details={"tool": tool_name},
                trace_id=trace_id,
            )
        missing = self._missing_dependencies(
            bool(getattr(definition, "mutating", False))
        )
        if missing:
            return fail_closed(details={"missing": missing}, trace_id=trace_id)
        assert self.auth is not None
        validation = self.auth.validate_session(
            session_token, require_csrf=csrf_token
        )
        if not validation.ok or validation.principal is None:
            return validation.decision
        principal = validation.principal
        mutating = bool(getattr(definition, "mutating", False))
        screening = self._screen_request(
            principal, request_text, mutating, dict(arguments or {})
        )
        if screening is not None and not screening.allowed:
            return screening.decision
        if screening is not None and screening.restricted and mutating:
            return SecurityDecision.block(
                SecurityCategory.SCREENING.value,
                ReasonCode.RESTRICTED_CAPABILITY,
                message="当前请求仅允许只读操作，状态变更已被阻止。",
                trace_id=trace_id,
            )
        authorized, _resources, _binding = self._authorize_tool(
            principal, tool_name, dict(arguments or {}), trace_id, phase="plan"
        )
        if authorized is None:
            return SecurityDecision.block(
                SecurityCategory.AUTHORIZATION.value,
                ReasonCode.UNKNOWN_ACTION,
                details={"tool": tool_name},
                trace_id=trace_id,
            )
        if authorized.allowed and getattr(definition, "mutating", False):
            return SecurityDecision.allow(
                SecurityCategory.AUTHORIZATION.value,
                "PLAN_ALLOWED_CONFIRMATION_REQUIRED",
                details={
                    **dict(authorized.details),
                    "requires_confirmation": True,
                    "tool": tool_name,
                },
                trace_id=trace_id,
            )
        return authorized

    # ------------------------------------------------------------------
    # Authorization helpers
    # ------------------------------------------------------------------

    def _authorize_tool(
        self,
        principal: Principal,
        tool_name: str,
        args: dict[str, Any],
        trace_id: str,
        *,
        phase: str,
    ) -> tuple[
        SecurityDecision | None,
        dict[str, ResolvedResource],
        dict[str, Any] | None,
    ]:
        assert self.authorization is not None
        actions = actions_for_tool(tool_name, phase=phase)
        if not actions:
            return None, {}, None

        resources: dict[str, ResolvedResource] = {}
        binding: dict[str, Any] | None = None
        review_required = False

        if tool_name == "execute_transaction":
            source_ref = ResourceRef("account", str(args.get("from_account_ref", "")))
            beneficiary_ref = ResourceRef(
                "beneficiary", str(args.get("beneficiary_name", ""))
            )
            source = self.authorization.resolve_resource(principal, source_ref)
            beneficiary = self.authorization.resolve_resource(
                principal, beneficiary_ref
            )
            if source is None or beneficiary is None:
                return (
                    SecurityDecision.block(
                        SecurityCategory.AUTHORIZATION.value,
                        ReasonCode.RESOURCE_NOT_FOUND,
                        message="未找到该账户或收款人，或不在当前授权范围内。",
                        trace_id=trace_id,
                        details={"tool": tool_name},
                    ),
                    {},
                    None,
                )
            resources["source"] = source
            resources["beneficiary"] = beneficiary
            for action in actions:
                decision = self.authorization.authorize(
                    principal,
                    action,
                    source_ref,
                    trace_id=trace_id,
                )
                if not decision.allowed:
                    return decision, resources, None
                review_required = review_required or decision.requires_review
            policy = self.transaction_policy.validate(
                principal,
                source=source,
                beneficiary=beneficiary,
                amount=args.get("amount", ""),
                currency=str(args.get("currency", "CNY")),
            )
            if not policy.allowed:
                return policy, resources, None
            binding = self._transaction_binding(
                args, source=source, beneficiary=beneficiary
            )
            if review_required:
                return (
                    SecurityDecision.allow(
                        SecurityCategory.AUTHORIZATION.value,
                        "TRANSACTION_AUTHORIZED_REVIEW_REQUIRED",
                        message="交易已通过授权，但需要人工复核。",
                        trace_id=trace_id,
                        details=dict(policy.details),
                        requires_review=True,
                    ),
                    resources,
                    binding,
                )
            return policy, resources, binding

        resource_ref: ResourceRef | None = None
        account_ref = args.get("account_ref")
        if account_ref:
            resource_ref = ResourceRef("account", str(account_ref))
        allow_unscoped = (
            resource_ref is None and tool_name in OPTIONAL_ACCOUNT_SCOPE_TOOLS
        )

        if tool_name == "create_alert" and resource_ref is None:
            allow_unscoped = True

        last: SecurityDecision | None = None
        for action in actions:
            decision = self.authorization.authorize(
                principal,
                action,
                resource_ref,
                allow_unscoped=allow_unscoped,
                trace_id=trace_id,
            )
            if not decision.allowed:
                return decision, resources, None
            review_required = review_required or decision.requires_review
            last = decision

        if resource_ref is not None:
            resolved = self.authorization.resolve_resource(principal, resource_ref)
            if resolved is None:
                return (
                    SecurityDecision.block(
                        SecurityCategory.AUTHORIZATION.value,
                        ReasonCode.RESOURCE_NOT_FOUND,
                        message="未找到该资源，或不在当前授权范围内。",
                        trace_id=trace_id,
                        details={"tool": tool_name},
                    ),
                    resources,
                    None,
                )
            resources["account"] = resolved

        if getattr(self._definition(tool_name), "mutating", False):
            binding = {
                "action": actions[-1],
                "resource_id": resources.get("account").resource_id
                if resources.get("account")
                else None,
                "parameters": self._canonical_parameters(args),
            }
        if review_required and last is not None and not last.requires_review:
            return (
                SecurityDecision.allow(
                    SecurityCategory.AUTHORIZATION.value,
                    "AUTHORIZED_REVIEW_REQUIRED",
                    message="操作已通过授权，但需要人工复核。",
                    trace_id=trace_id,
                    details=dict(last.details),
                    requires_review=True,
                ),
                resources,
                binding,
            )
        return last, resources, binding

    def _confirmation_binding(
        self,
        principal: Principal,
        tool_name: str,
        args: dict[str, Any],
        resources: dict[str, ResolvedResource],
        binding: dict[str, Any] | None,
        trace_id: str,
    ) -> tuple[str | None, str | None, dict[str, Any]]:
        if tool_name == "execute_transaction":
            source = resources.get("source")
            beneficiary = resources.get("beneficiary")
            if source is None or beneficiary is None:
                return None, None, {}
            parameters = self._transaction_binding(
                args, source=source, beneficiary=beneficiary
            )
            return "transaction.execute", source.resource_id, parameters
        if binding is None:
            return None, None, {}
        action = str(binding.get("action") or "")
        resource_id = binding.get("resource_id")
        parameters = dict(binding.get("parameters") or {})
        return action, resource_id, parameters

    @staticmethod
    def _transaction_binding(
        args: Mapping[str, Any],
        *,
        source: ResolvedResource,
        beneficiary: ResolvedResource,
    ) -> dict[str, Any]:
        amount = AuthorizedToolGateway._normalized_amount(args.get("amount"))
        currency = str(args.get("currency", "CNY")).upper()
        note = str(args.get("note", "") or "")
        return {
            "type": "transaction",
            "amount": amount,
            "currency": currency,
            "from_account_id": source.resource_id,
            "beneficiary_id": beneficiary.resource_id,
            "note_hash": hashlib.sha256(note.encode("utf-8")).hexdigest()[:16]
            if note
            else None,
        }

    @staticmethod
    def _normalized_amount(value: Any) -> str:
        try:
            return str(Decimal(str(value)).quantize(Decimal("0.01")))
        except (InvalidOperation, ValueError):
            return str(value)

    @staticmethod
    def _canonical_parameters(value: Any) -> dict[str, Any]:
        def normalise(item: Any) -> Any:
            if isinstance(item, Decimal):
                return str(item)
            if isinstance(item, Mapping):
                return {
                    str(key): normalise(val) for key, val in item.items()
                }
            if isinstance(item, (list, tuple)):
                return [normalise(entry) for entry in item]
            if isinstance(item, set):
                return sorted(normalise(entry) for entry in item)
            return item

        normalised = normalise(dict(value))
        # Round-trip through canonical JSON so the value has a stable shape.
        return normalised

    # ------------------------------------------------------------------
    # Screening / dependencies / audit
    # ------------------------------------------------------------------

    def _screen_request(
        self,
        principal: Principal,
        request_text: str,
        mutating: bool,
        arguments: Mapping[str, Any] | None = None,
    ) -> ScreeningResult | None:
        assert self.injection_guard is not None
        owned: set[str] = set()
        if self.authorization is not None:
            resolver = getattr(self.authorization, "resolver", None)
            if resolver is not None:
                try:
                    owned = resolver.owned_account_ids(principal.user_id)
                except Exception:
                    owned = set()
        context = {
            "principal": principal,
            "owned_resource_ids": sorted(owned),
        }
        user_screening = self.injection_guard.screen_input(
            request_text or "", context=context
        )
        if not arguments:
            return user_screening

        # Tool arguments can carry injection in free-text fields such as a
        # transaction note. Treat every argument object as untrusted data; a
        # blocked argument screen blocks dispatch. This applies to reads too,
        # because a query string is still untrusted input.
        argument_screening = self.injection_guard.screen_untrusted_content(
            canonical_json(
                self._canonical_parameters(arguments)
            ),
            source="tool_arguments",
            context=context,
        )
        if not argument_screening.allowed:
            return argument_screening
        if argument_screening.outcome == Decision.REQUIRE_REVIEW.value:
            return argument_screening
        if argument_screening.outcome == Decision.RESTRICT.value:
            return argument_screening
        return user_screening

    def _missing_dependencies(self, mutating: bool) -> list[str]:
        missing: list[str] = []
        if self.registry is None:
            missing.append("tool_registry")
        if self.auth is None:
            missing.append("authentication_provider")
        if self.authorization is None:
            missing.append("authorization_service")
        if self.injection_guard is None:
            missing.append("prompt_injection_guard")
        if self.output_guard is None:
            missing.append("output_guard")
        if mutating:
            if self.confirmation is None:
                missing.append("confirmation_service")
            if self.audit is None:
                missing.append("security_audit")
        return missing

    def _definition(self, tool_name: str) -> Any:
        if self.registry is None:
            return None
        try:
            return self.registry.get_definition(tool_name)
        except Exception:
            return None

    def _try_audit(
        self,
        event_type: str,
        decision: SecurityDecision,
        principal: Principal,
        details: Mapping[str, Any],
    ) -> str | None:
        try:
            event = self.audit.log(
                event_type,
                decision=decision,
                principal=principal,
                source="tool_gateway",
                details=dict(details),
            )
            return event.event_id
        except AuditUnavailableError:
            return None

    @staticmethod
    def _result(
        decision: SecurityDecision,
        trace_id: str,
        *,
        tool_result: ToolCallResult | None = None,
        output_validation: ToolOutputValidation | None = None,
        event_id: str | None = None,
    ) -> SecureToolResult:
        safe_data = (
            output_validation.safe_data
            if output_validation is not None
            and output_validation.allowed
            and isinstance(output_validation.safe_data, Mapping)
            else None
        )
        safe_tool_result = tool_result
        if (
            tool_result is not None
            and output_validation is not None
            and not output_validation.allowed
        ):
            # Never propagate a blocked tool payload to the orchestrator.
            safe_tool_result = copy.deepcopy(tool_result)
            safe_tool_result.data = {}
        return SecureToolResult(
            ok=decision.allowed,
            decision=decision,
            tool_result=safe_tool_result,
            safe_data=safe_data,
            output_validation=output_validation,
            trace_id=trace_id,
            security_event_id=event_id,
        )


# ----------------------------------------------------------------------
# Orchestrator wrapper
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class SecureAgentResponse:
    status: str
    text: str
    decision: SecurityDecision
    audit_id: str | None = None
    agent_status: str | None = None
    security_event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "text": self.text,
            "decision": self.decision.to_dict(),
            "audit_id": self.audit_id,
            "agent_status": self.agent_status,
            "security_event_id": self.security_event_id,
        }


class SecureAgentGateway:
    """Security wrapper around the existing legacy agent pipeline."""

    def __init__(
        self,
        agent: Any,
        auth_provider: AuthenticationProvider | None,
        injection_guard: PromptInjectionGuard | None,
        authorization: AuthorizationService | None = None,
        *,
        output_guard: OutputGuard | None = None,
        audit: SecurityAuditLogger | None = None,
        tool_gateway: AuthorizedToolGateway | None = None,
    ) -> None:
        self.agent = agent
        self.auth = auth_provider
        self.injection_guard = injection_guard
        self.authorization = authorization
        self.output_guard = output_guard or (
            OutputGuard(
                injection_guard,
                resolver=getattr(authorization, "resolver", None),
            )
            if injection_guard is not None
            else None
        )
        self.audit = audit or SecurityAuditLogger()
        self.tool_gateway = tool_gateway
        self._agent_sessions: dict[str, Session] = {}

    def login(
        self,
        username: str,
        password: str,
        *,
        device_id: str | None = None,
        transport: str = "bearer",
    ):
        from .auth import Credentials

        from .models import LoginResult

        if self.auth is None:
            return LoginResult(
                ok=False,
                decision=fail_closed(
                    details={"component": "authentication_provider"}
                ),
            )
        try:
            return self.auth.authenticate(
                Credentials(username, password),
                device_id=device_id,
                transport=transport,
            )
        except Exception as exc:
            return LoginResult(
                ok=False,
                decision=fail_closed(
                    details={
                        "component": "authentication_provider",
                        "exception_type": type(exc).__name__,
                    }
                ),
            )

    def logout(self, session_token: str) -> SecurityDecision:
        if self.auth is None:
            return fail_closed(details={"component": "authentication_provider"})
        try:
            validation = self.auth.validate_session(session_token)
            if validation.session is not None:
                self._agent_sessions.pop(validation.session.session_id, None)
            decision = self.auth.logout(session_token)
            self.audit.try_log(
                "AGENT_LOGOUT",
                decision=decision,
                source="orchestrator",
            )
            return decision
        except Exception as exc:
            return fail_closed(
                details={
                    "component": "authentication_provider",
                    "exception_type": type(exc).__name__,
                }
            )

    def handle(
        self,
        session_token: str,
        text: str,
        *,
        csrf_token: str | None = None,
    ) -> SecureAgentResponse:
        try:
            return self._handle_impl(
                session_token, text, csrf_token=csrf_token
            )
        except Exception as exc:
            return self._fail_response(
                fail_closed(
                    details={
                        "component": "orchestrator_security_layer",
                        "exception_type": type(exc).__name__,
                    }
                )
            )

    def _handle_impl(
        self,
        session_token: str,
        text: str,
        *,
        csrf_token: str | None = None,
    ) -> SecureAgentResponse:
        if self.auth is None or self.injection_guard is None or self.output_guard is None:
            return self._fail_response(
                fail_closed(
                    details={"component": "security_dependencies"}
                )
            )
        validation = self.auth.validate_session(
            session_token, require_csrf=csrf_token
        )
        if not validation.ok or validation.principal is None:
            return self._fail_response(validation.decision)
        principal = validation.principal

        screening = self.injection_guard.screen_input(
            text or "",
            context={
                "principal": principal,
                "owned_resource_ids": self._owned_account_ids(principal),
            },
        )
        self._try_audit("INPUT_SCREENED", screening.decision, principal, text)
        if screening.outcome == Decision.BLOCK.value:
            return SecureAgentResponse(
                status="rejected",
                text=screening.decision.message,
                decision=screening.decision,
                security_event_id=screening.decision.event_id,
            )
        if screening.outcome == Decision.REQUIRE_REVIEW.value:
            return SecureAgentResponse(
                status="needs_review",
                text=screening.decision.message,
                decision=screening.decision,
                security_event_id=screening.decision.event_id,
            )

        restricted = screening.outcome == Decision.RESTRICT.value
        scopes = set(principal.permissions) & LEGACY_SCOPES
        if restricted:
            scopes &= READ_ONLY_LEGACY_SCOPES
        legacy_session = self._legacy_session(principal, scopes, restricted)

        try:
            agent_response = self.agent.handle(legacy_session, text or "")
        except Exception:
            decision = SecurityDecision.block(
                SecurityCategory.DEPENDENCY.value,
                ReasonCode.TOOL_EXECUTION_FAILED,
                message="Agent 处理失败，操作未完成。",
            )
            return self._fail_response(decision)

        raw_text = getattr(agent_response, "text", "") or ""
        output = self.output_guard.validate_assistant_output(
            raw_text, principal, trace_id=screening.decision.trace_id
        )
        final_event = self._try_audit(
            "AGENT_RESPONSE_VALIDATED", output.decision, principal, text
        )
        if not output.allowed:
            return SecureAgentResponse(
                status="rejected",
                text=output.decision.message,
                decision=output.decision,
                audit_id=getattr(agent_response, "audit_id", None),
                agent_status=getattr(agent_response, "status", None),
                security_event_id=final_event or output.decision.event_id,
            )
        decision = SecurityDecision.allow(
            SecurityCategory.SCREENING.value,
            "AGENT_REQUEST_ALLOWED",
            message="请求已通过安全检查。",
            details={
                "restricted": restricted,
                "input_reason": screening.decision.reason_code,
            },
        )
        return SecureAgentResponse(
            status="completed",
            text=output.safe_text,
            decision=decision,
            audit_id=getattr(agent_response, "audit_id", None),
            agent_status=getattr(agent_response, "status", None),
            security_event_id=final_event,
        )

    def execute_tool(
        self,
        session_token: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        request_text: str = "",
        confirmation_id: str | None = None,
        csrf_token: str | None = None,
        expected_permission_version: int | None = None,
    ) -> SecureToolResult:
        if self.tool_gateway is None:
            return SecureToolResult(
                ok=False,
                decision=fail_closed(
                    details={"component": "authorized_tool_gateway"}
                ),
            )
        try:
            return self.tool_gateway.execute(
                session_token,
                tool_name,
                arguments,
                request_text=request_text,
                confirmation_id=confirmation_id,
                csrf_token=csrf_token,
                expected_permission_version=expected_permission_version,
            )
        except Exception as exc:
            return SecureToolResult(
                ok=False,
                decision=fail_closed(
                    details={
                        "component": "authorized_tool_gateway",
                        "exception_type": type(exc).__name__,
                    }
                ),
            )

    def check_tool(
        self,
        session_token: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        request_text: str = "",
        csrf_token: str | None = None,
    ) -> SecurityDecision:
        if self.tool_gateway is None:
            return fail_closed(details={"component": "authorized_tool_gateway"})
        try:
            return self.tool_gateway.check(
                session_token,
                tool_name,
                arguments,
                request_text=request_text,
                csrf_token=csrf_token,
            )
        except Exception as exc:
            return fail_closed(
                details={
                    "component": "authorized_tool_gateway",
                    "exception_type": type(exc).__name__,
                }
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _legacy_session(
        self, principal: Principal, scopes: set[str], restricted: bool
    ) -> Session:
        session = self._agent_sessions.get(principal.session_id)
        if session is None or session.customer_id != principal.user_id:
            session = Session(
                session_id=principal.session_id,
                customer_id=principal.user_id,
                identity_level=principal.auth_level,
                scopes=set(scopes),
            )
            self._agent_sessions[principal.session_id] = session
            return session

        new_scopes = set(scopes)
        if new_scopes != session.scopes or restricted:
            if session.pending is not None:
                try:
                    self.agent.risk.abandon(session.pending.risk_state, session)
                except Exception:
                    pass
                session.pending = None
            session.pending_clarification = None
            session.scopes = new_scopes
            session.identity_level = principal.auth_level
        return session

    def _owned_account_ids(self, principal: Principal) -> list[str]:
        if self.authorization is None:
            return []
        resolver = getattr(self.authorization, "resolver", None)
        if resolver is None:
            return []
        try:
            return sorted(resolver.owned_account_ids(principal.user_id))
        except Exception:
            return []

    def _try_audit(
        self,
        event_type: str,
        decision: SecurityDecision,
        principal: Principal,
        content: str,
    ) -> str | None:
        try:
            event = self.audit.log(
                event_type,
                decision=decision,
                principal=principal,
                source="orchestrator",
                content=content,
            )
            return event.event_id
        except AuditUnavailableError:
            return None

    @staticmethod
    def _fail_response(decision: SecurityDecision) -> SecureAgentResponse:
        return SecureAgentResponse(
            status="rejected",
            text=decision.message,
            decision=decision,
            security_event_id=decision.event_id,
        )
