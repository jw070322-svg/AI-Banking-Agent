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
