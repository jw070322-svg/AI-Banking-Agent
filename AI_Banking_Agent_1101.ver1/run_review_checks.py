"""Run current evidence without overwriting any inherited report."""
from pathlib import Path
import io,json,subprocess,sys,unittest
from unittest.mock import patch
from start import prepare_node

def main():
    node=prepare_node();root=Path(__file__).parent
    report=root/'reports/review-continuation';report.mkdir(exist_ok=True,parents=True)
    mode=sys.argv[1] if len(sys.argv)>1 else 'new'
    suite=unittest.defaultTestLoader.discover(str(root/'tests')) if mode=='inherited' else unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromName('review_additions.test_review'), unittest.defaultTestLoader.loadTestsFromName('review_additions.test_phase2')])
    stream=io.StringIO()
    with patch('first_agent.external_services.request',return_value={'status':'unavailable','reason':'offline_test'}):
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (report/(mode+'-tests.txt')).write_text(stream.getvalue())
    out={'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()}
    (report/(mode+'-tests.json')).write_text(json.dumps(out,indent=2))
    print(json.dumps(out));print(stream.getvalue()[-12000:] if not result.wasSuccessful() else '')
    scripts=sorted((root/'tests_frontend').glob('*.cjs')) if mode=='inherited' else [root/'review_additions/test_frontend.cjs']
    results=[]
    for p in scripts:
        run=subprocess.run([node,str(p)],capture_output=True,text=True)
        results.append({'file':p.name,'exit_code':run.returncode,'result':json.loads(run.stdout) if run.returncode==0 else run.stderr})
    frontend={'passed':all(r['exit_code']==0 for r in results),'results':results}
    (report/(mode+'-frontend-tests.json')).write_text(json.dumps(frontend,ensure_ascii=False,indent=2))
    print(json.dumps(frontend,ensure_ascii=False))
    return 0 if result.wasSuccessful() and frontend['passed'] else 1

if __name__=='__main__':sys.exit(main())
