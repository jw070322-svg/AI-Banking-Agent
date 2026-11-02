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
