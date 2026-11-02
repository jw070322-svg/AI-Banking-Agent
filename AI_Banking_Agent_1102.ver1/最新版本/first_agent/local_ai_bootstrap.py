"""Start or diagnose the Windows CPU model distributed inside this copy."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

VERSION_ROOT = Path(__file__).resolve().parents[1]
from first_agent.external_services import MODEL_PORT

TASK_ROOT = VERSION_ROOT / 'runtime'
STATUS_FILE = TASK_ROOT / 'local-ai-status.json'
RECEIPT = VERSION_ROOT / 'model-assets' / 'manifest.json'
SCRIPT = VERSION_ROOT / 'start_local_ai.ps1'

STATES = ('already_ready', 'started', 'refused_adapter', 'key_conflict',
          'port_conflict', 'timeout', 'failed', 'unavailable')

MESSAGES = {
    'already_ready': '本地模型已在运行',
    'started': '本地模型已启动',
    'refused_adapter': '训练适配器未能加载，已拒绝启动基础模型',
    'key_conflict': '端口被另一把密钥的模型服务占用，请先停止该进程',
    'port_conflict': '端口被另一个模型服务占用，请先停止该进程',
    'timeout': '本地模型启动超时',
    'failed': '本地模型启动失败',
    'unavailable': '本机不支持或缺少本地模型安装',
}


def _probe_models() -> tuple[bool, list[str], str]:
    """Return (reachable, model_ids, detail) for the local /v1/models call."""
    from first_agent.external_services import LLAMA, MODEL, request

    result = request(LLAMA + '/v1/models', timeout=3)
    status = result.get('status')
    if status == 'ok':
        try:
            ids = [str(item.get('id')) for item in json.loads(result['body'])['data']]
        except (ValueError, KeyError, TypeError):
            return True, [], 'malformed /v1/models payload'
        return True, ids, 'ready' if MODEL in ids else 'alias_missing'
    if status == 'auth_rejected':
        return True, [], 'auth_rejected'
    return False, [], str(result.get('reason') or status or 'unreachable')


def listening_pids(port: int = MODEL_PORT) -> list[int]:
    """PIDs listening on `port`, from netstat. Used only for the message text."""
    if os.name != 'nt':
        return []
    try:
        # 中文 Windows 的 netstat 输出是 GBK；用 replace 解码，避免整段丢弃。
        output = subprocess.run(['netstat', '-ano'], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    if not output:
        return []
    pattern = re.compile(rf'[:.]{port}\s+\S+\s+LISTENING\s+(\d+)', re.I)
    return sorted({int(m.group(1)) for m in pattern.finditer(output)})


def auth_enforced() -> dict:
    """A wrong key must be rejected; otherwise the server has no auth at all."""
    from first_agent.external_services import LLAMA, request

    result = request(LLAMA + '/v1/models', timeout=3, key='0' * 64)
    status = result.get('status')
    return {'enforced': status == 'auth_rejected', 'status': status,
            'http_status': result.get('http_status')}


def stop_process(pid: int) -> bool:
    """Stop a process this module started. Never called on a foreign process."""
    if not pid:
        return False
    try:
        subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True,
                       timeout=15)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def read_status_file() -> dict:
    try:
        return json.loads(STATUS_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _run_launcher(timeout: int) -> tuple[int | None, str, str]:
    """Run the launcher with output redirected to files, not pipes.

    Pipes would hang: the launcher detaches llama-server, which inherits the
    python->powershell pipe handles, so `communicate()` never sees EOF even
    after powershell exits. Files avoid that entirely.
    """
    command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
               '-File', str(SCRIPT)]
    out_path = TASK_ROOT / 'launcher.stdout.log'
    err_path = TASK_ROOT / 'launcher.stderr.log'
    try:
        TASK_ROOT.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'wb') as out, open(err_path, 'wb') as err:
            completed = subprocess.run(command, stdin=subprocess.DEVNULL,
                                       stdout=out, stderr=err,
                                       timeout=timeout, cwd=str(VERSION_ROOT))
        code = completed.returncode
    except subprocess.TimeoutExpired:
        return None, '', f'launcher exceeded {timeout}s'
    except OSError as exc:
        return None, '', f'{type(exc).__name__}: {exc}'
    read = lambda p: p.read_text(encoding='utf-8', errors='replace') if p.is_file() else ''
    return code, read(out_path), read(err_path)


def adapter_proof() -> dict:
    """Ask the running server which LoRA adapters it actually attached.

    The `--alias` flag is set whether or not the adapter loaded, so the alias is
    never proof. `/lora-adapters` is.
    """
    from first_agent.external_services import LLAMA, request

    result = request(LLAMA + '/lora-adapters', timeout=3)
    if result.get('status') != 'ok':
        return {'ok': False, 'source': 'unproven',
                'detail': f"lora-adapters probe: {result.get('status')}"}
    try:
        entries = json.loads(result['body'])
    except ValueError:
        return {'ok': False, 'source': 'unproven', 'detail': 'lora-adapters payload malformed'}
    if isinstance(entries, dict):
        entries = entries.get('adapters') or entries.get('data') or entries.get('items') or []
    wanted = 'adapter-qwen2.gguf'
    for item in entries or []:
        path = str(item.get('path') or item.get('name') or '')
        scale = item.get('scale', 1.0)
        if path.endswith(wanted) and float(scale or 0) != 0.0:
            return {'ok': True, 'source': 'lora-adapters',
                    'detail': f'{wanted} attached at scale {scale}', 'path': path}
    return {'ok': False, 'source': 'lora-adapters',
            'detail': f'{wanted} is not in the attached adapter list',
            'attached': entries}


def ensure_local_model(*, timeout: int = 45, runner=None) -> dict:
    """Bring the local model up if it is not already answering. Never raises."""
    started_at = time.monotonic()

    def result(state: str, detail: str, **extra) -> dict:
        return {'state': state, 'message': MESSAGES.get(state, state),
                'detail': detail, 'elapsed': round(time.monotonic() - started_at, 2),
                'status_file': str(STATUS_FILE), **extra}

    if os.name != 'nt':
        return result('unavailable', 'local model launcher is Windows-only')
    if not SCRIPT.is_file():
        return result('unavailable', f'launcher script missing: {SCRIPT}')
    if not RECEIPT.is_file():
        return result('unavailable', f'install receipt missing: {RECEIPT}')

    reachable, ids, detail = _probe_models()
    if reachable and detail == 'ready':
        proof = adapter_proof()
        if not proof['ok']:
            # 有人在用 LoRA 别名提供未微调的基础模型；这不是我们起的进程，
            # 所以只报告、不强杀。
            return result('refused_adapter', proof['detail'], models=ids,
                          adapter_proof=proof, auth=auth_enforced())
        return result('already_ready', 'banking-finance-lora answered /v1/models',
                      models=ids, adapter_proof=proof, auth=auth_enforced())

    run = runner or _run_launcher
    code, stdout, stderr = run(timeout)

    status = read_status_file()
    state = str(status.get('state') or '')

    if code is None:
        return result('timeout', stderr or 'launcher did not return')

    if state in ('started', 'already_ready') and code == 0:
        # 启动成功不等于适配器真加载：用 /lora-adapters 复核。
        proof = adapter_proof()
        if not proof['ok']:
            if state == 'started':
                stop_process(int(status.get('pid') or 0))
            return result('refused_adapter', proof['detail'], adapter_proof=proof)
        return result(state, str(status.get('detail') or ''), models=ids,
                      exit_code=code, pid=status.get('pid'),
                      key_source=status.get('key_source'),
                      adapter_proof=proof, auth=auth_enforced())

    if state in STATES and state not in ('already_ready', 'started'):
        payload = {k: status.get(k) for k in ('pid', 'key_source', 'adapter', 'stderr_tail')
                   if status.get(k) is not None}
        payload['exit_code'] = code
        if state in ('key_conflict', 'port_conflict'):
            payload['listening_pids'] = listening_pids()
            payload['hint'] = '先核对占用 8811 的进程，再重试；本工具不会自动杀进程'
        return result(state, str(status.get('detail') or ''), **payload)

    return result('failed', (stderr or stdout or detail).strip()[:400], exit_code=code)


def main() -> int:
    outcome = ensure_local_model()
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    return 0 if outcome['state'] in ('already_ready', 'started') else 1


if __name__ == '__main__':
    sys.exit(main())
