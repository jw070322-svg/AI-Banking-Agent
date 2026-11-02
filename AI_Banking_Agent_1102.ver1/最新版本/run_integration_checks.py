from pathlib import Path
import io,json,sys,unittest
from unittest.mock import patch
from start import prepare_node

if __name__=='__main__':
    prepare_node()
    root=Path(__file__).resolve().parent
    report=root/'reports/latest-integration-tests.txt'
    stream=io.StringIO();suite=unittest.defaultTestLoader.discover(str(root/'tests'))
    with patch('first_agent.external_services.request',return_value={'status':'unavailable','reason':'offline_test'}):
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    report.parent.mkdir(exist_ok=True);report.write_text(stream.getvalue(),encoding='utf-8')
    print(stream.getvalue())
    (root/'reports/latest-integration-tests.json').write_text(json.dumps({'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()},ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)
