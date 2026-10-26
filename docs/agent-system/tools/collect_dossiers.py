"""Fetch synthetic dossiers over HTTP; never load a generator database or JSON store."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ('R1', 'A', '生成一个普通银行用户，包含工资收入和日常消费'),
    ('R2', 'C', '生成一个疑似重复扣款的用户'),
    ('R3', 'D', '生成一个余额不足导致转账失败的场景'),
    ('R4', 'E', '生成一个周期性订阅扣费的场景'),
    ('R5', 'F', '检测我配偶的生日，锁定1000元活动预算并生成活动日历'),
]


def request(base_url, payload=None, key=None):
    path = '/api/scenarios/generate' if payload is not None else '/api/health'
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Idempotency-Key'] = key
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    with urllib.request.urlopen(urllib.request.Request(base_url + path, data=data, headers=headers), timeout=30) as response:
        raw = response.read()
    return json.loads(raw), raw


def collect(base_url, reference_date):
    health, _ = request(base_url)
    assert health['ready'], 'Environment API is unavailable'
    dossiers = []
    evidence = []
    output = ROOT / 'examples'
    output.mkdir(exist_ok=True)
    raw_output = ROOT / 'reports' / 'raw-environment-responses'
    raw_output.mkdir(parents=True, exist_ok=True)
    for index, (dossier_id, scenario_type, prompt) in enumerate(CASES, start=1):
        payload = {'prompt': prompt, 'scenario_type': scenario_type, 'seed': 2700 + index, 'reference_date': reference_date}
        key = f'system-prompt-1027-{reference_date}-{dossier_id}'
        envelope, raw = request(base_url, payload, key)
        assert envelope['status'] == 'succeeded', envelope.get('error')
        assert envelope['simulated'] is True
        data = envelope['data']
        assert data['ledger_modified'] is False
        assert data['scenario_type'] == scenario_type
        accounts = data['accounts']
        transactions = data['transactions']
        for account in accounts:
            movements = sum(t['amount'] for t in transactions if t['account_id'] == account['account_id'] and t['status'] == 'booked')
            assert account['initial_balance_minor'] + movements == account['balance_minor'], 'Ledger reconciliation failed'
        for transaction in transactions:
            assert type(transaction['amount']) is int and type(transaction['amount_minor']) is int
            assert abs(transaction['amount']) == transaction['amount_minor']
        raw_file = raw_output / f'{dossier_id}.json'
        raw_file.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        dossier = {
            'schema_version': 'banking.dossier.v1',
            'dossier_id': dossier_id,
            'scenario_type': scenario_type,
            'scenario_id': data['scenario_id'],
            'source': {'provider': 'environment-agent', 'mode': 'synthetic', 'transport': 'HTTP',
                       'endpoint': '/api/scenarios/generate', 'request_id': envelope['request_id'],
                       'retrieved_at': datetime.now(timezone.utc).isoformat(),
                       'raw_response_sha256': digest, 'raw_response_path': str(raw_file.relative_to(ROOT)).replace('\\', '/')},
            'reference_date': reference_date,
            'seed': payload['seed'],
            'simulated': True,
            'ledger_modified': False,
            'customer': data.get('user'),
            'risk_profile': None,
            'risk_profile_status': 'not_provided_by_api',
            'accounts': accounts,
            'activity_summary': {'booked_income_minor': sum(t['amount'] for t in transactions if t['status'] == 'booked' and t['amount'] > 0),
                                 'booked_outflow_minor': -sum(t['amount'] for t in transactions if t['status'] == 'booked' and t['amount'] < 0),
                                 'transaction_count': len(transactions)},
            'recent_activity': [{k: v for k, v in t.items() if k not in {'expected_result', 'expected_insights', 'evaluation_only_fields'}}
                                for t in sorted(transactions, key=lambda t: t['date'], reverse=True)[:3]],
            'calendar': data.get('activity_calendar', []),
            'budget': data.get('budget'),
            'data_quality': {'balance_reconciled': True, 'money_unit': 'CNY_minor_integer', 'missing_fields': ['risk_profile'],
                             'notes': ['R1-R5 are dossier identifiers, not customer or product risk ratings.',
                                       'Full authoritative generation response is retained locally with its hash; this is an abbreviated audit example.']},
        }
        (output / f'{dossier_id}.json').write_text(json.dumps(dossier, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        dossiers.append(dossier)
        repeated, _ = request(base_url, payload, key)
        assert repeated['request_id'] == envelope['request_id'], 'Idempotency replay failed'
        assert repeated['data'] == data, 'Idempotency changed the data'
        evidence.append({'dossier_id': dossier_id, 'scenario_type': scenario_type, 'http_api_succeeded': True,
                         'reconciled_accounts': len(accounts), 'transactions': len(transactions), 'idempotency_replayed': True,
                         'raw_response_sha256': digest})
    (output / 'dossiers.json').write_text(json.dumps({'schema_version': 'banking.dossier-collection.v1', 'dossiers': dossiers}, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'base_url': base_url,
              'mode': 'synthetic_HTTP_API', 'passed': True, 'evidence': evidence}
    (ROOT / 'reports' / 'dossier-api-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'dossiers': [{'dossier_id': x['dossier_id'], 'scenario_type': x['scenario_type'], 'transactions': x['activity_summary']['transaction_count']} for x in dossiers]}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8792')
    parser.add_argument('--reference-date', default='2026-10-27')
    arguments = parser.parse_args()
    collect(arguments.base_url.rstrip('/'), arguments.reference_date)
