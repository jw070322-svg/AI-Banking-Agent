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
