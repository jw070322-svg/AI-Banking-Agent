"""Local model connection: key precedence, status mapping, bootstrap state machine.

No sockets, no process spawn, no real llama.cpp. Patches at the module boundary.
"""
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from first_agent import external_services as ext
from first_agent import local_ai_bootstrap as boot


class KeyResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.shared = root / 'local-ai' / 'local-model.key'
        self.legacy = root / 'version' / 'runtime' / 'local-model.key'
        self.shared.parent.mkdir(parents=True)
        self.legacy.parent.mkdir(parents=True)
        patcher = patch.object(ext, 'MODEL_KEY_CANDIDATES', (self.shared, self.legacy))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_shared_key_wins_when_both_exist(self):
        self.shared.write_text('shared-value', encoding='utf-8')
        self.legacy.write_text('legacy-value', encoding='utf-8')
        path, value = ext.model_key()
        self.assertEqual(path, self.shared)
        self.assertEqual(value, 'shared-value')

    def test_legacy_key_is_fallback_when_shared_missing(self):
        self.legacy.write_text('legacy-value', encoding='utf-8')
        path, value = ext.model_key()
        self.assertEqual(path, self.legacy)
        self.assertEqual(value, 'legacy-value')

    def test_no_candidate_returns_empty(self):
        self.assertEqual(ext.model_key(), (None, ''))

    def test_empty_shared_file_falls_through_to_legacy(self):
        self.shared.write_text('   \n', encoding='utf-8')
        self.legacy.write_text('legacy-value', encoding='utf-8')
        self.assertEqual(ext.model_key()[1], 'legacy-value')

    def test_unreadable_key_does_not_escape(self):
        # 非 UTF-8 字节过去会在 try 之外抛 UnicodeDecodeError，变 HTTP 500。
        self.shared.write_bytes(b'\xff\xfe\x00binary')
        self.assertEqual(ext.model_key(), (None, ''))


class RequestHeaderTests(unittest.TestCase):
    """Targets the pure header builder: the integration runner replaces
    `external_services.request` wholesale to keep the suite offline, so tests
    must not go through it."""

    def test_authorization_header_sent_when_key_present(self):
        with patch.object(ext, 'model_key', lambda: (Path('x'), 'secret-key')):
            is_local, headers = ext.local_request_headers(ext.LLAMA + '/v1/models')
        self.assertTrue(is_local)
        self.assertEqual(headers.get('Authorization'), 'Bearer secret-key')

    def test_no_header_when_no_key(self):
        with patch.object(ext, 'model_key', lambda: (None, '')):
            _, headers = ext.local_request_headers(ext.LLAMA + '/v1/models')
        self.assertNotIn('Authorization', headers)

    def test_key_override_is_used(self):
        with patch.object(ext, 'model_key', lambda: (Path('x'), 'real-key')):
            _, headers = ext.local_request_headers(ext.LLAMA + '/v1/models', key='probe-key')
        self.assertEqual(headers.get('Authorization'), 'Bearer probe-key')

    def test_non_loopback_path_is_blocked(self):
        with self.assertRaises(ValueError):
            ext.local_request_headers('http://127.0.0.1:8811/admin')

    def test_public_https_is_allowed_and_has_no_authorization(self):
        is_local, headers = ext.local_request_headers('https://www.baidu.com/s?wd=x')
        self.assertFalse(is_local)
        self.assertNotIn('Authorization', headers)


class StatusMappingTests(unittest.TestCase):
    def test_local_401_maps_to_auth_rejected(self):
        result = ext.http_error_result(True, 401)
        self.assertEqual(result['status'], 'auth_rejected')
        self.assertEqual(result['http_status'], 401)

    def test_local_403_maps_to_auth_rejected(self):
        self.assertEqual(ext.http_error_result(True, 403)['status'], 'auth_rejected')

    def test_public_401_still_needs_verification(self):
        result = ext.http_error_result(False, 401)
        self.assertEqual(result['status'], 'needs_verification')

    def test_public_429_still_needs_verification(self):
        self.assertEqual(ext.http_error_result(False, 429)['status'], 'needs_verification')

    def test_auth_rejected_label_is_distinct(self):
        self.assertIn('auth_rejected', ext.LABELS)
        self.assertNotEqual(ext.LABELS['auth_rejected'], ext.LABELS['needs_verification'])


class BootstrapTests(unittest.TestCase):
    def run_bootstrap(self, *, probe, runner, status=None, proof=None, stop=None):
        patches = [
            patch.object(boot, '_probe_models', lambda: probe),
            patch.object(boot, 'read_status_file', lambda: status or {}),
            patch.object(boot, 'SCRIPT', Path(__file__)),
            patch.object(boot, 'RECEIPT', Path(__file__)),
            patch.object(boot, 'listening_pids', lambda *a, **k: []),
        ]
        if proof is not None:
            patches.append(patch.object(boot, 'adapter_proof', lambda: proof))
        if stop is not None:
            patches.append(patch.object(boot, 'stop_process', stop))
        for p in patches:
            p.start()
        try:
            with patch.object(boot.os, 'name', 'nt'):
                return boot.ensure_local_model(runner=runner)
        finally:
            for p in patches:
                p.stop()

    def test_already_ready_skips_launcher(self):
        called = []
        outcome = self.run_bootstrap(
            probe=(True, ['banking-finance-lora'], 'ready'),
            runner=lambda t: called.append(t) or (0, '', ''),
            proof={'ok': True, 'source': 'lora-adapters', 'detail': 'attached'})
        self.assertEqual(outcome['state'], 'already_ready')
        self.assertEqual(called, [], 'launcher must not run when the model already answers')

    def test_refused_adapter_when_alias_served_without_adapter(self):
        outcome = self.run_bootstrap(
            probe=(True, ['banking-finance-lora'], 'ready'),
            runner=lambda t: (0, '', ''),
            proof={'ok': False, 'source': 'lora-adapters', 'detail': 'adapter missing'})
        self.assertEqual(outcome['state'], 'refused_adapter')

    def test_started_requires_adapter_proof(self):
        stopped = []
        outcome = self.run_bootstrap(
            probe=(False, [], 'unreachable'),
            runner=lambda t: (0, 'started', ''),
            status={'state': 'started', 'pid': 4321, 'key_source': 'shared'},
            proof={'ok': False, 'source': 'lora-adapters', 'detail': 'not attached'},
            stop=lambda pid: stopped.append(pid) or True)
        self.assertEqual(outcome['state'], 'refused_adapter')
        self.assertEqual(stopped, [4321], 'our own process must be stopped when the adapter is absent')

    def test_started_when_proof_passes(self):
        outcome = self.run_bootstrap(
            probe=(False, [], 'unreachable'),
            runner=lambda t: (0, 'started', ''),
            status={'state': 'started', 'pid': 99, 'key_source': 'shared'},
            proof={'ok': True, 'source': 'lora-adapters', 'detail': 'attached'},
            stop=lambda pid: True)
        self.assertEqual(outcome['state'], 'started')
        self.assertEqual(outcome['pid'], 99)
        self.assertEqual(outcome['key_source'], 'shared')

    def test_port_conflict_reports_and_does_not_launch(self):
        called = []
        outcome = self.run_bootstrap(
            probe=(False, [], 'unreachable'),
            runner=lambda t: called.append(t) or (4, '', ''),
            status={'state': 'key_conflict', 'detail': 'different key'})
        self.assertEqual(outcome['state'], 'key_conflict')
        self.assertIn('hint', outcome)

    def test_missing_adapter_status_is_surfaced(self):
        outcome = self.run_bootstrap(
            probe=(False, [], 'unreachable'),
            runner=lambda t: (2, '', ''),
            status={'state': 'refused_adapter', 'detail': 'adapter file missing'})
        self.assertEqual(outcome['state'], 'refused_adapter')

    def test_timeout_when_launcher_does_not_return(self):
        outcome = self.run_bootstrap(
            probe=(False, [], 'unreachable'),
            runner=lambda t: (None, '', 'launcher exceeded 45s'))
        self.assertEqual(outcome['state'], 'timeout')


class ImportSideEffectTests(unittest.TestCase):
    def test_importing_bootstrap_starts_nothing(self):
        with patch.object(boot.subprocess, 'run') as run:
            importlib.reload(boot)
            run.assert_not_called()

    def test_importing_start_starts_nothing(self):
        with patch('first_agent.local_ai_bootstrap.ensure_local_model') as ensure:
            import start  # noqa: F401
            ensure.assert_not_called()


if __name__ == '__main__':
    unittest.main()
