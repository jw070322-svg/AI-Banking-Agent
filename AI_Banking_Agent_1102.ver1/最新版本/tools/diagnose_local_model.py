"""Answer one question: which link in the local-model chain is broken?

Checks, in the order they can fail:
  1. key files      - shared first, legacy second
  2. port 8811      - is anything listening at all
  3. /v1/models     - unauthenticated and authenticated, and the alias it reports
  4. adapter file   - present, size, and the SHA-256 the training run produced
  5. last status    - whatever the launcher left behind

Read-only: it never starts or stops a process. Run:

    python tools/diagnose_local_model.py
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from first_agent.external_services import (  # noqa: E402
    LLAMA, MODEL, MODEL_KEY_CANDIDATES, model_key, request,
)
from first_agent.local_ai_bootstrap import (  # noqa: E402
    MODEL_PORT, STATUS_FILE, listening_pids, read_status_file,
)

ADAPTER = BASE / 'training/lora-finance-qwen05b-full/adapter-qwen2.gguf'
ADAPTER_SHA256 = 'ce77779a64722866b8d5cede0ee2c0485345a020d195a3a2abed7e592f10bad6'


def sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def models_call(label: str, **kwargs) -> dict:
    result = request(LLAMA + '/v1/models', timeout=3, **kwargs)
    status = result.get('status')
    aliases: list[str] = []
    if status == 'ok':
        try:
            aliases = [str(item.get('id')) for item in json.loads(result['body'])['data']]
        except (ValueError, KeyError, TypeError):
            status = 'malformed'
    return {'check': label, 'status': status, 'http_status': result.get('http_status'),
            'reason': result.get('reason'), 'aliases': aliases,
            'has_expected_alias': MODEL in aliases}


def main() -> int:
    report: dict = {'report': 'local-model-diagnosis'}

    keys = []
    for path in MODEL_KEY_CANDIDATES:
        keys.append({'path': str(path), 'exists': path.is_file(),
                     'bytes': path.stat().st_size if path.is_file() else 0,
                     'sha256_12': sha256(path)[:12] if path.is_file() else None})
    chosen_path, chosen_value = model_key()
    report['keys'] = {'candidates': keys,
                      'chosen': str(chosen_path) if chosen_path else None,
                      'chosen_sha256_12': sha256(chosen_path)[:12] if chosen_path else None}

    with socket.socket() as probe:
        probe.settimeout(1.5)
        port_open = probe.connect_ex(('127.0.0.1', MODEL_PORT)) == 0
    report['port'] = {'port': MODEL_PORT, 'listening': port_open,
                      'pids': listening_pids()}

    report['models_without_key'] = models_call('no_key', key='')
    report['models_with_key'] = models_call('with_key')
    from first_agent.local_ai_bootstrap import adapter_proof, auth_enforced
    report['lora_adapters'] = adapter_proof()
    report['auth_enforced'] = auth_enforced()

    report['adapter'] = {
        'path': str(ADAPTER),
        'exists': ADAPTER.is_file(),
        'bytes': ADAPTER.stat().st_size if ADAPTER.is_file() else 0,
        'sha256_matches_training_output': (sha256(ADAPTER) == ADAPTER_SHA256) if ADAPTER.is_file() else False,
    }
    report['last_launcher_status'] = read_status_file()

    with_key = report['models_with_key']
    ready = (with_key['status'] == 'ok' and with_key['has_expected_alias']
             and report['lora_adapters']['ok'] and report['auth_enforced']['enforced']
             and report['adapter']['sha256_matches_training_output'])
    report['conclusion'] = 'ready' if ready else _conclusion(report)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ready else 1


def _conclusion(report: dict) -> str:
    if not report['port']['listening']:
        return '服务未运行：先运行 python -m first_agent.local_ai_bootstrap 或启动演示入口'
    if report['models_with_key']['status'] == 'auth_rejected':
        return '服务在跑但密钥不匹配：本副本密钥与运行中的服务不一致'
    if not report['models_with_key'].get('has_expected_alias'):
        return '服务在跑但没有 banking-finance-lora 这个别名'
    if not report['lora_adapters']['ok']:
        return f"别名在，但适配器未挂载：{report['lora_adapters']['detail']}"
    if not report['adapter']['exists']:
        return '训练适配器缺失，启动器会拒绝启动'
    return '未就绪，见上面各项'


if __name__ == '__main__':
    sys.exit(main())
