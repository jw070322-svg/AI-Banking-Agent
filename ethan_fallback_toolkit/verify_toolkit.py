"""Run meaningful contract/regression tests; save exact results to reports."""
from pathlib import Path
from datetime import datetime,timezone
import io,json,sys,unittest

ROOT=Path(__file__).resolve().parent


def main():
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    reports=ROOT/'reports';reports.mkdir(exist_ok=True)
    (reports/'tests.txt').write_text(stream.getvalue(),encoding='utf-8')
    failed={str(t) for t,_ in result.failures+result.errors+result.skipped}
    report={'verified_at_utc':datetime.now(timezone.utc).isoformat(),'run':result.testsRun,'passed':result.testsRun-len(failed),
            'failures':[str(t) for t,_ in result.failures],'errors':[str(t) for t,_ in result.errors],
            'skipped':[str(t) for t,_ in result.skipped],'conclusion':'passed' if result.wasSuccessful() else 'failed'}
    (reports/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not result.wasSuccessful():print(stream.getvalue())
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':sys.exit(main())
