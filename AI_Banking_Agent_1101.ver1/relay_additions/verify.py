"""Offline reports in a NEW folder; never overwrite inherited test evidence."""
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from start import prepare_node
from review_additions import evaluate

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/relay-1030'


def main():
    REPORT.mkdir(parents=True,exist_ok=True)
    node=prepare_node();summaries={}
    for name,suite in [
        ('teammate',unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in ['review_additions.test_review','review_additions.test_phase2'])),
        ('relay',unittest.defaultTestLoader.loadTestsFromName('relay_additions.test_boundaries')),
        ('inherited',unittest.defaultTestLoader.discover(str(ROOT/'tests')))]:
        stream=io.StringIO()
        with patch('first_agent.external_services.request',return_value={'status':'unavailable','reason':'offline_verification'}),patch.object(evaluate,'REPORT',REPORT):
            result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
        (REPORT/(name+'-tests.txt')).write_text(stream.getvalue(),encoding='utf-8')
        summaries[name]={'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()}
        print(name,json.dumps(summaries[name]),flush=True)
    frontend=[]
    for script in [*sorted((ROOT/'tests_frontend').glob('*.cjs')),ROOT/'review_additions/test_frontend.cjs',ROOT/'relay_additions/test_frontend.cjs']:
        run=subprocess.run([node,str(script)],capture_output=True,text=True,encoding='utf-8')
        frontend.append({'script':str(script.relative_to(ROOT)),'code':run.returncode,'stdout':run.stdout,'stderr':run.stderr})
    (REPORT/'frontend.json').write_text(json.dumps(frontend,ensure_ascii=False,indent=2),encoding='utf-8')
    summaries['frontend']={'scripts':len(frontend),'passed':all(r['code']==0 for r in frontend)}
    (REPORT/'tests.json').write_text(json.dumps(summaries,indent=2),encoding='utf-8')
    print('frontend',summaries['frontend'],flush=True)
    return 0 if all(v['passed'] for v in summaries.values()) else 1


if __name__=='__main__': raise SystemExit(main())
