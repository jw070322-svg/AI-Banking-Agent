"""Exercise the running portable web app and its local inference service."""
import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from first_agent.external_services import ExternalServices, LLAMA, request
from first_agent.local_ai_bootstrap import adapter_proof, auth_enforced


def verify(port):
    origin = f'http://127.0.0.1:{port}'
    client = build_opener(ProxyHandler({}), HTTPCookieProcessor())

    def call(path, body=None):
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {'Content-Type': 'application/json', 'Idempotency-Key': uuid.uuid4().hex}
        with client.open(Request(origin + path, data=payload, headers=headers), timeout=65) as response:
            return json.load(response)

    proof = adapter_proof()
    no_key = request(LLAMA + '/v1/models', key='')
    wrong_key = auth_enforced()
    if not proof['ok'] or not wrong_key['enforced'] or no_key['status'] != 'auth_rejected':
        raise RuntimeError('Adapter or credential challenge failed')
    direct = ExternalServices().complete('只回答用户要求的词语。', '只回复“收到”。', max_tokens=48)
    if direct['status'] != 'ok' or not direct.get('answer'):
        raise RuntimeError('Local inference returned no complete answer')
    call('/api/session', {})
    response = call('/api/knowledge', {'question': '什么是相空间嵌入维数'})
    result = response.get('data') or {}
    if not result.get('model_response_received') or result.get('external_data_sent') is not False:
        raise RuntimeError('Web knowledge request did not complete via the offline model: ' +
                           str((response.get('error'), result.get('status'), result.get('fallback_steps'))))
    return {'at': datetime.now(timezone.utc).isoformat(), 'app_port': port, 'model_url': LLAMA,
            'model': direct['model'], 'adapter': proof['detail'], 'no_key_http': no_key['http_status'],
            'wrong_key_http': wrong_key['http_status'], 'completion': direct['answer'],
            'web_route': '/api/knowledge', 'web_status': result['status'],
            'web_model_received': True, 'external_data_sent': False, 'steps': result['fallback_steps']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8808)
    print(json.dumps(verify(parser.parse_args().port), ensure_ascii=False, indent=2))
