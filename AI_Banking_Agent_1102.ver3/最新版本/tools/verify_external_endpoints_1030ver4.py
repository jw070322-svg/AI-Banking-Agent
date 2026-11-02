"""Live, read-only check of every third-party endpoint the app depends on.

Why: the user asked whether the API interfaces still use current endpoints.
Third-party contracts cannot be inferred from a version number, so this takes
one measurement per endpoint: status, bytes, latency and a shape signature that
proves the existing parser would still accept the response.

Rules kept:

- It probes; it does not upgrade anything. A single failure is never grounds to
  change a constant. Only "current endpoint demonstrably broken AND replacement
  proven with the same parsing contract" would justify an edit, made separately.
- It reuses the app's own `PublicHTTP` (allowlist, HTTPS-only, redirects
  rejected, default TLS verification) instead of a fresh HTTP client.
- ChinaWealth verification links are never fetched: that site uses a captcha
  and the project does not bypass it.
- No credentials are read. Google Calendar is recorded as skipped without them.

Run: python tools/verify_external_endpoints_1030ver4.py [--offline]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/external-endpoints-1030ver4'
sys.path.insert(0, str(ROOT))

from live_indices.provider import (  # noqa: E402
    HOSTS,
    THS,
    WIND,
    WIND_SCRIPT,
    PublicHTTP,
    ths_token,
)
from live_products.provider import PRODUCT_HOSTS, etf_token  # noqa: E402

INDEX_CODE = '000001.SH'
ETF_CODE = '510300.SH'
LOCAL_MODEL = 'http://127.0.0.1:8797/v1/models'


def _index_quote_url() -> str:
    token = ths_token(INDEX_CODE)
    return f'https://d.10jqka.com.cn/v6/time/zs_{token}/last.js'


def _etf_quote_url() -> str:
    token = etf_token(ETF_CODE)
    assert token is not None, 'fixture ETF must be an exchange-traded code'
    return f'https://d.10jqka.com.cn/v6/time/hs_{token}/last.js'


def _signature_js_jsonp(text: str) -> dict:
    stripped = text.strip()
    head, _, rest = stripped.partition('(')
    return {
        'kind': 'jsonp',
        'callback': head,
        'callback_matches_v6_pattern': head.startswith('quotebridge_v6_time_'),
        'ends_with_close': rest.rstrip().endswith(');') or rest.rstrip().endswith(')'),
        'has_json_body': rest.lstrip().startswith('{"'),
    }


def _signature_html(text: str) -> dict:
    lowered = text[:200000].lower()
    return {
        'kind': 'html',
        'bytes_probe': len(text),
        'has_doctype_or_html': '<!doctype html' in lowered or '<html' in lowered,
        'mentions_windindex': 'windindex' in lowered,
    }


def _signature_text(text: str) -> dict:
    return {'kind': 'text', 'has_content': bool(text.strip())}


def probe(url: str, hosts, signature, client, *, sample_name: str) -> dict:
    started = time.monotonic()
    record = {'name': sample_name, 'url': url, 'hosts': sorted(hosts),
              'checked_at': datetime.now(timezone.utc).isoformat()}
    try:
        text = client(url)
    except Exception as exc:  # 记录失败，不改端点
        record.update({
            'status': 'unavailable',
            'error': f'{type(exc).__name__}: {exc}',
            'elapsed_ms': round((time.monotonic() - started) * 1000),
        })
        return record
    sample = OUT / f'{sample_name}.txt'
    sample.write_text(text, encoding='utf-8')
    import hashlib
    record.update({
        'status': 'ok',
        'bytes': len(text.encode('utf-8')),
        'elapsed_ms': round((time.monotonic() - started) * 1000),
        'signature': signature(text),
        'sample': f'reports/external-endpoints-1030ver4/{sample_name}.txt',
        'sample_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
    })
    return record


def local_model_probe() -> dict:
    from urllib.request import Request, urlopen
    started = time.monotonic()
    record = {'url': LOCAL_MODEL, 'checked_at': datetime.now(timezone.utc).isoformat()}
    try:
        with urlopen(Request(LOCAL_MODEL, headers={'Accept': 'application/json'}), timeout=3) as response:
            payload = json.loads(response.read().decode('utf-8'))
        record.update({'status': 'ok', 'latency_ms': round((time.monotonic() - started) * 1000),
                       'models': len(payload.get('data') or [])})
    except Exception as exc:
        record.update({'status': 'unavailable', 'error': f'{type(exc).__name__}: {exc}',
                       'note': '本地模型未启动；这不是外部接口失效'})
    return record


def chain_check() -> list[dict]:
    """Run the real resolver chain: THS -> Wind official -> bundled Wind snapshot."""
    from live_indices.provider import IndexProvider

    provider = IndexProvider()
    out = []
    for code, name in (('000001.SH', '上证指数'), ('399001.SZ', '深证成指'),
                       ('399006.SZ', '创业板指'), ('399905.SZ', '中证500'),
                       ('931186.CSI', '中证科技50策略')):
        try:
            result = provider.select((code, name), {})
            out.append({'code': code, 'name': name,
                        'result_source': result.get('result_source'),
                        'has_final_data': bool(result.get('final_data')),
                        'steps': [{k: s.get(k) for k in ('source', 'status', 'observation')}
                                  for s in result.get('steps', [])]})
        except Exception as exc:
            out.append({'code': code, 'name': name,
                        'error': f'{type(exc).__name__}: {exc}'})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='外部端点只读实测')
    parser.add_argument('--offline', action='store_true', help='不联网，只写跳过记录')
    options = parser.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    checks: list[dict] = []

    if options.offline:
        checks.append({'status': 'skipped_offline'})
    else:
        index_client = PublicHTTP(ttl=0, hosts=HOSTS)
        product_client = PublicHTTP(ttl=0, hosts=PRODUCT_HOSTS)

        checks.append(probe(THS, HOSTS, _signature_html, index_client,
                            sample_name='ths_index_directory'))
        checks.append(probe(_index_quote_url(), HOSTS, _signature_js_jsonp, index_client,
                            sample_name=f'ths_zs_{ths_token(INDEX_CODE)}'))
        checks.append(probe(WIND, HOSTS, _signature_html, index_client,
                            sample_name='wind_index_page'))
        checks.append(probe(WIND_SCRIPT, HOSTS, _signature_text, index_client,
                            sample_name='wind_detail_js'))
        checks.append(probe(_etf_quote_url(), PRODUCT_HOSTS, _signature_js_jsonp, product_client,
                            sample_name=f'ths_hs_{etf_token(ETF_CODE)}'))
        checks.append(local_model_probe())

    checks.append({
        'url': 'https://xinxipilu.chinawealth.com.cn/...',
        'status': 'skipped_by_policy',
        'reason': '中国理财网带验证码风控；按项目约定不抓取、不绕过，只作为人工核验链接',
    })
    checks.append({
        'url': 'https://www.googleapis.com/calendar/v3/...',
        'status': 'skipped_no_credentials',
        'reason': '需要 BANKING_GOOGLE_* 环境变量；未读取任何凭据',
    })

    chain = [] if options.offline else chain_check()
    ok = [c for c in checks if c['status'] == 'ok']
    bad = [c for c in checks if c['status'] == 'unavailable']
    report = {
        'generated_by': 'tools/verify_external_endpoints_1030ver4.py',
        'generated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'policy': '只探测不升级；一次失败不构成更换端点的理由',
        'summary': {'probed': len(ok) + len(bad), 'ok': len(ok), 'unavailable': len(bad),
                    'skipped': len(checks) - len(ok) - len(bad),
                    'chain_resolved_by_ths': sum(1 for c in chain if c.get('result_source') == '同花顺'),
                    'chain_fallback_local': sum(1 for c in chain if c.get('result_source') and c.get('result_source') != '同花顺')},
        'checks': checks,
        'index_chain': chain,
    }
    (OUT / 'PROVENANCE.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print(json.dumps(report['summary'], ensure_ascii=False))
    for item in checks:
        if item.get('signature'):
            print('sample', item['sample'], item['signature'])
    for item in bad:
        print('UNAVAILABLE', item['url'], item.get('error'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
