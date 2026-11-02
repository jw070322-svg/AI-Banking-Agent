# tools calling 与 security 新增完整代码

基底与测试说明见 TOOLS_SECURITY_README.md。以下逐文件完整输出，不省略函数。仅新增文件；原输入源码不改。

## first_agent/vendor/eva/security/compatibility.py

【补全内容（first_agent/vendor/eva/security/compatibility.py）起】

``````python
"""Bridge the 1029 scanner interface to the preserved banking application."""
from first_agent.security import Scanner


class CompatibleScanner(Scanner):
    def scan_input(self, text, *, ignore_code_blocks=False):
        # The older scanner does not have a code-block exemption. Keep its
        # complete scan, including code blocks, rather than silently weaken it.
        return super().scan_input(text)

    def scan_untrusted_content(self, source, content):
        return self.scan_input(content, ignore_code_blocks=False)

``````

【补全内容（first_agent/vendor/eva/security/compatibility.py）止】

## first_agent/vendor/eva/security/hardening.py

【补全内容（first_agent/vendor/eva/security/hardening.py）起】

``````python
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

``````

【补全内容（first_agent/vendor/eva/security/hardening.py）止】

## first_agent/vendor/eva/security/quota_handoff.py

【补全内容（first_agent/vendor/eva/security/quota_handoff.py）起】

``````python
"""Development quota guard. Account usage is supplied by a trusted host callback.

Bank customers and LLM arguments cannot supply or override this callback.
No credentials, account ID, or private reasoning are written to the handoff.
"""
import json
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path


class QuotaPaused(RuntimeError):
    pass


class QuotaGuard:
    def __init__(self, provider, output_path, *, user_id='JW', threshold=15, clock=None):
        self.provider, self.output_path = provider, Path(output_path)
        self.user_id, self.threshold = user_id, threshold
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def check(self, operations=(), next_steps=()):
        """Snapshot {observed_at: ISO8601, windows: {name: remaining_percent}}.

        Unknown/stale usage pauses too, but is never represented as zero credit.
        Existing project rule uses <=15, a conservative boundary for <15.
        """
        reason, windows = '', {}
        try:
            snapshot = self.provider()
            observed = datetime.fromisoformat(snapshot['observed_at'])
            now = self.clock()
            if observed.tzinfo is None or not 0 <= (now - observed).total_seconds() <= 300:
                raise ValueError('stale usage')
            windows = snapshot['windows']
            if not isinstance(windows, dict) or not windows:
                raise ValueError('usage unavailable')
            if any(type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 100
                   for value in windows.values()):
                raise ValueError('invalid usage')
            if min(windows.values()) <= self.threshold:
                reason = '任一可信额度窗口剩余小于或等于15%，按项目约定暂停。'
        except Exception:
            windows, reason = {}, '未取得新鲜可信的额度，暂停新的业务与GitHub写操作。'
        if not reason:
            return windows
        payload = {'用户ID': self.user_id, '剩余额度': windows or None,
            '状态': 'paused', '暂停原因': reason,
            '操作记录': list(operations), '后续处理建议': list(next_steps) + [
                '仅保存必要本地交接与审计；不要继续业务修改、测试或GitHub写操作。',
                '用户明确继续后重新读取交接，核验所有可信额度窗口均高于15%。'],
            'timestamp': self.clock().astimezone(timezone(timedelta(hours=8))).isoformat()}
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output_path.with_suffix(self.output_path.suffix + '.tmp')
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.output_path)
        raise QuotaPaused(reason)

``````

【补全内容（first_agent/vendor/eva/security/quota_handoff.py）止】

## first_agent/vendor/eva/security/runtime.py

【补全内容（first_agent/vendor/eva/security/runtime.py）起】

``````python
"""Explicit server-side assembly of Module 6 and 8; no import-time actions."""
from dataclasses import dataclass
from pathlib import Path

from ..tool_calling.hardening import HardenedToolRegistry
from ..tool_calling.services import ToolServices
from .audit import JsonlSecurityAudit, SecurityAuditLogger
from .auth import MockAuthenticationProvider
from .authorization import AuthorizationService
from .hardening import HardenedToolGateway, LockedConfirmationService
from .injection import OutputGuard, PromptInjectionGuard
from .resources import MockBankResourceResolver
from .compatibility import CompatibleScanner


@dataclass
class SecurityRuntime:
    registry: HardenedToolRegistry
    gateway: HardenedToolGateway
    auth: object
    audit: SecurityAuditLogger


def build_runtime(directory, *, users=(), auth_provider=None, services=None,
                  risk_engine=None, compliance_guard=None, step_up_verifier=None):
    """Compose compatible ports. Default data/identity remain explicit demos.

    No auto-enable of mock safety or real payments. Production adapters remain
    unverified unless independently configured; missing R4 controls deny calls.
    Do not expose registry/auth administration to a model or browser client.
    """
    directory = Path(directory)
    services = services if services is not None else ToolServices.demo()
    scanner = CompatibleScanner()
    audit = SecurityAuditLogger(JsonlSecurityAudit(directory / 'security-audit', scanner=scanner), scanner=scanner)
    auth = auth_provider if auth_provider is not None else MockAuthenticationProvider(users, audit=audit)
    registry = HardenedToolRegistry(services, journal_path=directory / 'tool-dispatch.sqlite3',
        risk_engine=risk_engine, compliance_guard=compliance_guard)
    resolver = MockBankResourceResolver(services.bank, services.planning)
    guard = PromptInjectionGuard(scanner)
    confirmation = LockedConfirmationService(audit=audit, step_up_verifier=step_up_verifier)
    gateway = HardenedToolGateway(registry, auth, AuthorizationService(resolver),
        injection_guard=guard, confirmation=confirmation,
        output_guard=OutputGuard(guard, resolver=resolver), audit=audit)
    return SecurityRuntime(registry, gateway, auth, audit)

``````

【补全内容（first_agent/vendor/eva/security/runtime.py）止】

## first_agent/vendor/eva/security/selfcheck.py

【补全内容（first_agent/vendor/eva/security/selfcheck.py）起】

``````python
"""Run reproducible local checks without overwriting any inherited report."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description='1029 tools/security 自检；仅使用模拟数据')
    parser.add_argument('--scope', choices=['modules', 'all'], default='modules')
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    from start import prepare_node
    node = prepare_node()
    pattern = 'test_*.py' if options.scope == 'all' else 'test_tools_security_1029.py'
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern=pattern)
    stream = io.StringIO()
    with patch('first_agent.external_services.request', return_value={'status': 'unavailable', 'reason': 'offline_test'}):
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report = {'scope': options.scope, 'backend': {'run': result.testsRun,
              'failures': len(result.failures), 'errors': len(result.errors),
              'passed': result.wasSuccessful()}, 'frontend': None}
    if options.scope == 'all':
        outcomes = []
        for path in sorted((root / 'tests_frontend').glob('*.cjs')):
            proc = subprocess.run([node, str(path)], capture_output=True, text=True,
                                  encoding='utf-8', timeout=90, cwd=root)
            outcomes.append({'file': path.name, **(json.loads(proc.stdout) if proc.returncode == 0
                                                   else {'error': proc.stderr})})
        report['frontend'] = {'passed': all('error' not in item for item in outcomes),
                             'total': sum(item.get('passed', 0) for item in outcomes),
                             'results': outcomes}
    report['passed'] = report['backend']['passed'] and (report['frontend'] is None or report['frontend']['passed'])
    target = root / 'reports' / ('1029-' + options.scope + '-selfcheck')
    target.with_suffix('.txt').write_text(stream.getvalue(), encoding='utf-8')
    target.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    if not result.wasSuccessful():
        print(stream.getvalue())
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

``````

【补全内容（first_agent/vendor/eva/security/selfcheck.py）止】

## first_agent/vendor/eva/tool_calling/hardening.py

【补全内容（first_agent/vendor/eva/tool_calling/hardening.py）起】

``````python
"""Additive contract bounds and durable mutation admission; original registry intact.

The ledger is a dispatch journal, not a bank ledger. It prevents a second
dispatch after uncertain execution. It cannot make an external side effect and
a local SQLite commit atomic; interrupted calls require receipt reconciliation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from threading import RLock

from .errors import ToolErrorDetail, ToolLayerError
from .models import ToolCallContext, ToolCallResult, make_call_id
from .registry import ToolRegistry
from .utils import now_iso


def bounded_json(value, *, maximum_bytes=65536):
    """Reject non-JSON, nonfinite, cyclic/deep and oversized input before use."""
    count = 0

    def visit(item, depth=0):
        nonlocal count
        count += 1
        if depth > 16 or count > 4096:
            raise ValueError('JSON complexity limit exceeded')
        if item is None or type(item) in (bool, int, str):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError('JSON keys must be strings')
            for child in item.values():
                visit(child, depth + 1)
            return
        if type(item) is list:
            for child in item:
                visit(child, depth + 1)
            return
        raise ValueError('Only finite JSON values are accepted')

    visit(value)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':'), allow_nan=False)
    if len(raw.encode('utf-8')) > maximum_bytes:
        raise ValueError('JSON size limit exceeded')
    return raw


def fingerprint(value):
    return hashlib.sha256(bounded_json(value).encode('utf-8')).hexdigest()


class MutationJournal:
    """Atomic cross-instance reservation. Stores hashes/status, never arguments."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS tool_dispatch (
                identity TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
                status TEXT NOT NULL, call_id TEXT NOT NULL, updated_at TEXT NOT NULL)''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def reserve(self, identity, request_hash, call_id):
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row = db.execute('SELECT request_hash,status,call_id FROM tool_dispatch WHERE identity=?',
                                 (identity,)).fetchone()
                if row:
                    db.commit()
                    return row
                db.execute('INSERT INTO tool_dispatch VALUES(?,?,?,?,?)',
                           (identity, request_hash, 'started', call_id, now_iso()))
                db.commit()
                return None
            except BaseException:
                db.rollback()
                raise

    def finish(self, identity, status, call_id):
        with closing(self.connect()) as db:
            db.execute('UPDATE tool_dispatch SET status=?,call_id=?,updated_at=? WHERE identity=?',
                       (status, call_id, now_iso(), identity))


class HardenedToolRegistry(ToolRegistry):
    """Same execute signature/envelope, adds bounded input and at-most-one dispatch.

Direct use is server-side only. Untrusted callers must go through
HardenedToolGateway; context/permissions are never accepted from model JSON.
"""
    def __init__(self, *args, journal_path, **kwargs):
        super().__init__(*args, **kwargs)
        self.journal = MutationJournal(journal_path)
        self._dispatch_lock = RLock()
        self._completed = {}

    def normalize(self, name, arguments):
        raw = {} if arguments is None else arguments
        bounded_json(raw)
        if type(raw) is not dict:
            raise ValueError('Tool arguments must be an object')
        definition = self._definitions.get(name)
        if definition is None:
            raise ToolLayerError('TOOL_NOT_FOUND', '未注册的工具。')
        return self._normalize_arguments(definition, copy.deepcopy(raw))

    def _reject(self, name, context, code, *, unknown=False, duplicate=False):
        definition = self._definitions.get(name)
        return ToolCallResult(
            tool=name, version=definition.version if definition else '',
            call_id=make_call_id(), ok=False, status='unknown' if unknown else 'error',
            error=ToolErrorDetail(code, '调用未再次执行；请检查参数、授权或核对原操作回执。', False),
            meta={'trace_id': context.trace_id, 'phase': 'additive_guard',
                  'duplicate': duplicate, 'requires_reconciliation': unknown,
                  'simulated': definition.simulated if definition else True})

    def execute(self, name, arguments=None, context=None):
        if not isinstance(context, ToolCallContext):
            raise TypeError('an authenticated ToolCallContext is required')
        if not isinstance(name, str) or len(name) > 100:
            return self._reject('', context, 'TOOL_NOT_FOUND')
        try:
            normalized = self.normalize(name, arguments)
        except ToolLayerError as exc:
            return self._reject(name, context, exc.code)
        except (ValueError, TypeError, RecursionError):
            return self._reject(name, context, 'INVALID_ARGUMENTS')
        definition = self._definitions[name]
        if not definition.mutating:
            return super().execute(name, normalized, context)
        # Authorization is rechecked even for a cached response.
        try:
            self._check_permissions(definition, context)
            self._check_confirmation(definition, context)
        except ToolLayerError as exc:
            return self._reject(name, context, exc.code)
        key = context.idempotency_key
        if not isinstance(key, str) or not key.strip() or len(key) > 256:
            return self._reject(name, context, 'IDEMPOTENCY_KEY_REQUIRED')
        identity = fingerprint([context.user_id, context.session_id, key.strip()])
        request_hash = fingerprint([name, definition.version, normalized])
        # Serialize this registry's handlers, including inherited MockBank writes.
        with self._dispatch_lock:
            try:
                prior = self.journal.reserve(identity, request_hash, make_call_id())
            except sqlite3.Error:
                return self._reject(name, context, 'DISPATCH_JOURNAL_UNAVAILABLE')
            if prior:
                if prior[0] != request_hash:
                    return self._reject(name, context, 'IDEMPOTENCY_CONFLICT')
                cached = self._completed.get(identity)
                if cached is not None:
                    replay = copy.deepcopy(cached)
                    replay.meta.update(duplicate=True, trace_id=context.trace_id)
                    return replay
                return self._reject(name, context, 'RECONCILIATION_REQUIRED',
                                    unknown=True, duplicate=True)
            try:
                # Namespace the inherited in-memory cache as well.
                result = super().execute(name, normalized, replace(context, idempotency_key=identity))
            except Exception:
                result = self._reject(name, context, 'MUTATION_OUTCOME_UNKNOWN', unknown=True)
            try:
                self.journal.finish(identity, result.status, result.call_id)
            except sqlite3.Error:
                return self._reject(name, context, 'MUTATION_OUTCOME_UNKNOWN', unknown=True)
            self._completed[identity] = copy.deepcopy(result)
            return result

    # The original class binds aliases at class creation. Rebind them here so
    # callers using the documented aliases cannot skip the added journal.
    invoke = execute
    call = execute

``````

【补全内容（first_agent/vendor/eva/tool_calling/hardening.py）止】

## first_agent/vendor/eva/tool_calling/model_bridge.py

【补全内容（first_agent/vendor/eva/tool_calling/model_bridge.py）起】

``````python
"""One-way model suggestions: strict JSON, allowlist, trusted session, no callbacks.

This module never queries a model or network. The application supplies a model
response only after its own user-initiated model request. Mutating suggestions
are proposals; the separate authenticated user confirmation path is required.
"""
import json
import re

from .hardening import bounded_json


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def parse_arguments(raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 65536:
        raise ValueError('arguments must be a bounded JSON string')
    result = json.loads(raw, object_pairs_hook=_unique_object,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    bounded_json(result)
    if type(result) is not dict:
        raise ValueError('arguments must be an object')
    return result


class ModelToolBridge:
    def __init__(self, gateway):
        self.gateway = gateway

    def descriptors(self, session_token, *, csrf_token=None):
        validation = self.gateway.auth.validate_session(session_token, require_csrf=csrf_token)
        if not validation.ok or validation.principal is None:
            return []
        permissions = validation.principal.permissions
        return [{'type': 'function', 'function': {
                    'name': item['name'], 'description': item['description'],
                    'parameters': item['input_schema']}}
                for item in self.gateway.registry.discover()
                if set(item['permissions']).issubset(permissions)]

    def dispatch(self, session_token, tool_calls, *, request_text='', csrf_token=None):
        """Accept a bounded OpenAI-style tool_calls list; never model credentials."""
        try:
            bounded_json(tool_calls)
            if type(tool_calls) is not list or not 1 <= len(tool_calls) <= 8:
                raise ValueError('invalid batch')
            calls, seen = [], set()
            for call in tool_calls:
                if type(call) is not dict or set(call) != {'id', 'type', 'function'}:
                    raise ValueError('invalid call envelope')
                call_id = call['id']
                if not isinstance(call_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', call_id) or call_id in seen:
                    raise ValueError('invalid call id')
                seen.add(call_id)
                fn = call['function']
                if call['type'] != 'function' or type(fn) is not dict or set(fn) != {'name', 'arguments'}:
                    raise ValueError('invalid function')
                if type(fn['name']) is not str or not re.fullmatch(r'[a-z][a-z0-9_]{0,99}', fn['name']):
                    raise ValueError('invalid function name')
                args = parse_arguments(fn['arguments'])
                # Validate the whole batch before dispatching even the first read.
                args = self.gateway.registry.normalize(fn['name'], args)
                calls.append((call_id, fn['name'], args))
        except Exception:
            return {'ok': False, 'error': 'INVALID_TOOL_CALLS', 'results': []}
        results = []
        for call_id, name, args in calls:
            definition = self.gateway.registry._definitions[name]
            if definition.mutating:
                decision = self.gateway.check(session_token, name, args,
                    request_text=request_text, csrf_token=csrf_token)
                result = {'ok': False, 'status': 'confirmation_required' if decision.allowed else 'blocked',
                          'decision': decision.to_dict(), 'executed': False}
            else:
                result = self.gateway.execute(session_token, name, args,
                    request_text=request_text, csrf_token=csrf_token).to_dict()
            results.append({'tool_call_id': call_id, 'name': name, 'result': result})
        return {'ok': all(item['result']['ok'] for item in results), 'results': results}

``````

【补全内容（first_agent/vendor/eva/tool_calling/model_bridge.py）止】
