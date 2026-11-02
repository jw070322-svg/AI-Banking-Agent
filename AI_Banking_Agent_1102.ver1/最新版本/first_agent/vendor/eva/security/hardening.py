"""Additive gateway: normalize before confirmation; expose only guarded output."""
from __future__ import annotations

import copy
from dataclasses import replace
from threading import RLock

from ..tool_calling.hardening import bounded_json
from .confirmation import ConfirmationResult, ConfirmationService
from .gateway import AuthorizedToolGateway, SecureToolResult
from .models import SecurityDecision, new_security_id
from .sessions import ensure_aware, parse_iso


class _ConfirmedRegistryPort:
    """Carry step-up proof from the consumed server record, never model flags."""
    def __init__(self, registry, confirmation):
        self._registry, self._confirmation = registry, confirmation
        self.dispatched_mutation = False
        self.last_result = None

    def __getattr__(self, name):
        return getattr(self._registry, name)

    def execute(self, name, arguments, context):
        service = self._confirmation
        verified = False
        if service is not None and context.confirmation_id:
            with service._lock:
                record = service._get(context.confirmation_id)
                verified = bool(record and record.used_at and record.confirmed_at and
                    not record.cancelled_at and record.step_up_verified and
                    record.user_id == context.user_id and record.session_id == context.session_id and
                    parse_iso(record.expires_at) > ensure_aware(service.clock()))
        self.dispatched_mutation = self._registry.get_definition(name).mutating
        self.last_result = self._registry.execute(name, arguments, replace(context, step_up_verified=verified))
        return self.last_result


class LockedConfirmationService(ConfirmationService):
    """Keep record validation and state transitions in one existing RLock."""
    def confirm(self, *args, **kwargs):
        with self._lock:
            return super().confirm(*args, **kwargs)

    def consume(self, *args, **kwargs):
        with self._lock:
            return super().consume(*args, **kwargs)

    def cancel(self, *args, **kwargs):
        with self._lock:
            return super().cancel(*args, **kwargs)


class HardenedToolGateway(AuthorizedToolGateway):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.registry is not None:
            self.registry = _ConfirmedRegistryPort(self.registry, self.confirmation)
        self._transition_lock = RLock()

    @staticmethod
    def _blocked(code):
        return SecurityDecision.block('authorization', code,
            message='安全检查未通过；未授权本次调用。', trace_id=new_security_id('TRACE'))

    def _normalized(self, tool_name, arguments, request_text):
        if type(tool_name) is not str or len(tool_name) > 100:
            raise ValueError('invalid tool name')
        if type(request_text) is not str or len(request_text) > 8000:
            raise ValueError('invalid request text')
        bounded_json(arguments if arguments is not None else {})
        return self.registry.normalize(tool_name, arguments)

    def execute(self, session_token, tool_name, arguments=None, *, request_text='',
                confirmation_id=None, csrf_token=None, expected_permission_version=None):
        with self._transition_lock:
            if self.registry is not None:
                self.registry.dispatched_mutation = False
                self.registry.last_result = None
            try:
                normalized = self._normalized(tool_name, arguments, request_text)
            except Exception:
                decision = self._blocked('INVALID_ARGUMENTS')
                return self._result(decision, decision.trace_id)
            result = super().execute(session_token, tool_name, normalized,
                request_text=request_text, confirmation_id=confirmation_id,
                csrf_token=csrf_token, expected_permission_version=expected_permission_version)
            prior = self.registry.last_result
            if (not result.ok and self.registry.dispatched_mutation and
                    (prior is None or prior.ok or prior.status == 'unknown')):
                decision = replace(result.decision, requires_review=True,
                    message='操作可能已执行，后续处理未完成；请核对原回执，勿重复提交。',
                    details={**dict(result.decision.details), 'mutation_may_have_executed': True})
                result = replace(result, decision=decision)
            return result

    def check(self, session_token, tool_name, arguments=None, *, request_text='', csrf_token=None):
        try:
            normalized = self._normalized(tool_name, arguments, request_text)
        except Exception:
            return self._blocked('INVALID_ARGUMENTS')
        return super().check(session_token, tool_name, normalized,
                             request_text=request_text, csrf_token=csrf_token)

    def prepare_confirmation(self, session_token, tool_name, arguments=None, *,
                             request_text='', csrf_token=None):
        """Resolve and display exact normalized parameters using trusted identity."""
        with self._transition_lock:
            try:
                args = self._normalized(tool_name, arguments, request_text)
                decision = self.check(session_token, tool_name, args,
                                      request_text=request_text, csrf_token=csrf_token)
                if not decision.allowed or decision.requires_review:
                    return ConfirmationResult(False, decision)
                definition = self._definition(tool_name)
                if not definition.mutating or self.confirmation is None:
                    return ConfirmationResult(False, self._blocked('CONFIRMATION_NOT_APPLICABLE'))
                validation = self.auth.validate_session(session_token, require_csrf=csrf_token)
                if not validation.ok or validation.principal is None:
                    return ConfirmationResult(False, validation.decision)
                principal = validation.principal
                authorized, resources, binding = self._authorize_tool(
                    principal, tool_name, args, decision.trace_id, phase='execute')
                if authorized is None or not authorized.allowed or authorized.requires_review:
                    return ConfirmationResult(False, authorized or self._blocked('AUTHORIZATION_DENIED'))
                action, resource, parameters = self._confirmation_binding(
                    principal, tool_name, args, resources, binding, decision.trace_id)
                display = {'tool': tool_name, 'version': definition.version,
                           'parameters': parameters, 'simulated': definition.simulated}
                return self.confirmation.prepare(principal, action=action,
                    resource_id=resource, parameters=parameters, display_details=display,
                    requires_step_up=definition.risk_tier == 'R4')
            except Exception:
                return ConfirmationResult(False, self._blocked('CONFIRMATION_UNAVAILABLE'))

    def confirm(self, session_token, confirmation_id, *, presented_details,
                csrf_token=None, step_up_assertion_id=None):
        """Only an authenticated user-facing action calls this; never the model."""
        try:
            bounded_json(presented_details)
            if type(presented_details) is not dict:
                raise ValueError('display details required')
            validation = self.auth.validate_session(session_token, require_csrf=csrf_token)
            if not validation.ok or validation.principal is None:
                return ConfirmationResult(False, validation.decision)
            return self.confirmation.confirm(validation.principal, confirmation_id,
                presented_details=presented_details, step_up_assertion_id=step_up_assertion_id)
        except Exception:
            return ConfirmationResult(False, self._blocked('CONFIRMATION_INVALID'))

    @staticmethod
    def _result(decision, trace_id, *, tool_result=None, output_validation=None, event_id=None):
        # Original to_dict included raw tool_result.data even after redaction.
        # Return a detached sanitized object; never retain raw evidence payload.
        safe_data = None
        if decision.allowed and output_validation is not None and output_validation.allowed:
            safe_data = copy.deepcopy(output_validation.safe_data)
        safe_result = copy.deepcopy(tool_result)
        if safe_result is not None:
            safe_result.data = copy.deepcopy(safe_data or {})
            safe_result.evidence = None
            safe_result.meta = {key: value for key, value in safe_result.meta.items()
                                if key in {'phase', 'duplicate', 'simulated', 'requires_reconciliation'}}
            if safe_result.error is not None:
                safe_result.error = replace(safe_result.error,
                    message='工具未完成，请根据错误代码核对状态。', details={})
        validation = output_validation
        if validation is not None and safe_data is None:
            validation = replace(validation, safe_data=None)
        if safe_result is not None and safe_result.status == 'unknown':
            decision = replace(decision, requires_review=True,
                               message='执行结果未知；请核对原操作回执，勿重复提交。')
        elif decision.details.get('mutation_executed'):
            decision = replace(decision, requires_review=True,
                               message='操作可能已执行，但后续审计未完成；请核对回执，勿重复提交。')
        return SecureToolResult(ok=decision.allowed, decision=decision,
            tool_result=safe_result, safe_data=safe_data, output_validation=validation,
            trace_id=trace_id, security_event_id=event_id)
