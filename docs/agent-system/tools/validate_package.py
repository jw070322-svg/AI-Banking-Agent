"""Validate JSON artifacts and locally retained HTTP evidence; no model eval is implied."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def read(path):
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run():
    checks = []
    files = [p for p in ROOT.rglob('*.json') if 'runtime' not in p.parts]
    for path in files:
        read(path)
    checks.append({'check': 'strict_json_no_duplicates_or_nonfinite', 'passed': True, 'files': len(files)})
    collection = read(ROOT / 'examples/dossiers.json')['dossiers']
    mapping = read(ROOT / 'contracts/integration_contract.json')['dossier_id_mapping']
    assert {d['dossier_id'] for d in collection} == {'R1', 'R2', 'R3', 'R4', 'R5'}
    for dossier in collection:
        dossier_id = dossier['dossier_id']
        assert dossier == read(ROOT / 'examples' / f'{dossier_id}.json')
        raw_path = ROOT / dossier['source']['raw_response_path']
        assert raw_path.resolve().is_relative_to(ROOT)
        assert digest(raw_path) == dossier['source']['raw_response_sha256']
        response = read(raw_path)
        assert response['status'] == 'succeeded' and response['simulated'] is True
        assert response['request_id'] == dossier['source']['request_id']
        data = response['data']
        assert data['scenario_type'] == dossier['scenario_type'] == mapping[dossier_id]
        assert data['ledger_modified'] is False and dossier['ledger_modified'] is False
        assert dossier['risk_profile'] is None
        assert dossier['customer'] == data['user']
        transactions = data['transactions']
        for transaction in transactions:
            assert type(transaction['amount']) is int and type(transaction['amount_minor']) is int
            assert abs(transaction['amount']) == transaction['amount_minor']
        for account in data['accounts']:
            net = sum(t['amount'] for t in transactions if t['account_id'] == account['account_id'] and t['status'] == 'booked')
            assert account['initial_balance_minor'] + net == account['balance_minor']
        assert dossier['activity_summary']['transaction_count'] == len(transactions)
        assert dossier['activity_summary']['booked_income_minor'] == sum(t['amount'] for t in transactions if t['status'] == 'booked' and t['amount'] > 0)
        assert dossier['activity_summary']['booked_outflow_minor'] == -sum(t['amount'] for t in transactions if t['status'] == 'booked' and t['amount'] < 0)
        assert len(dossier['recent_activity']) <= 3
        for activity in dossier['recent_activity']:
            assert not {'expected_result', 'expected_insights', 'evaluation_only_fields'} & activity.keys()
        checks.append({'check': dossier_id + '_source_hash_units_reconciliation', 'passed': True})
    api_report = read(ROOT / 'reports/dossier-api-verification.json')
    assert api_report['passed'] and len(api_report['evidence']) == 5
    assert all(row['http_api_succeeded'] and row['idempotency_replayed'] for row in api_report['evidence'])
    checks.append({'check': 'retained_live_HTTP_and_idempotency_evidence', 'passed': True})
    wind = read(ROOT / 'contracts/wind_agent_guide.json')
    assert set(wind['workbook']['sheets']) == {'products', 'prices', 'risk_free', 'indices', 'macro'}
    assert len(wind['product_universe']) == 5 and wind['vendor_official_api_schema'] is False
    assert wind['workbook']['sheets']['products']['types']['min_amount'].startswith('number CNY yuan')
    checks.append({'check': 'wind_delivery_five_sheets_and_unit_contract', 'passed': True})
    contract = read(ROOT / 'contracts/integration_contract.json')
    assert contract['quota']['threshold_remaining_percent'] == 15 and contract['quota']['comparison'] == '<='
    assert all(not contract[key] for key in ('live_bank_verified', 'real_wind_verified', 'external_ai_verified', 'meituan_dianping_api_verified'))
    evaluations = read(ROOT / 'contracts/behavior_evaluations.json')
    assert evaluations['execution_status'] == 'specified_not_run_against_a_model'
    checks.append({'check': 'reserved_vs_verified_and_quota_policy_contract', 'passed': True})
    schemas = read(ROOT / 'contracts/tool_schemas.json')
    audit = schemas['$defs']['audit_record']
    log_fields = {'user_id', 'intent', 'tool', 'input', 'output', 'risk_check', 'approval', 'timestamp'}
    assert set(audit['required']) == log_fields and audit['additionalProperties'] is False
    logs = ROOT / 'development_log.jsonl'
    if logs.exists():
        for line in logs.read_text(encoding='utf-8').splitlines():
            row = json.loads(line, object_pairs_hook=pairs)
            assert set(row) == log_fields
    checks.append({'check': 'eight_field_log_contract', 'passed': True})
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'passed': True,
              'checks': checks, 'model_evaluations_run': 0,
              'note': 'Artifact/HTTP evidence verification only; no claim of runtime integration or full JSON Schema meta-validation.'}
    (ROOT / 'reports/package-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'checks': len(checks), 'model_evaluations_run': 0}, ensure_ascii=False))


if __name__ == '__main__':
    run()
