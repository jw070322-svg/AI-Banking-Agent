from pathlib import Path
import io,json,unittest
from datetime import datetime,timezone
from .evidence import source_fingerprint
from unittest.mock import patch
from start import prepare_node

def main():
    prepare_node()
    root=Path(__file__).resolve().parents[1]/'reports/security-integration-1101'
    root.mkdir(parents=True,exist_ok=True)
    started_at=datetime.now(timezone.utc).isoformat()
    stream=io.StringIO();suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromName('security_integration.test_chain'),unittest.defaultTestLoader.loadTestsFromName('security_integration.test_fixes')])
    with patch('first_agent.external_services.request',return_value={'status':'unavailable','reason':'offline_test'}):
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (root/'http-tests.txt').write_text(stream.getvalue())
    summary={'started_at':started_at,'completed_at':datetime.now(timezone.utc).isoformat(),'source_fingerprint':source_fingerprint(root.parents[1]),'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()}
    (root/'http-tests.json').write_text(json.dumps(summary,indent=2));print(summary)
    if not result.wasSuccessful():print(stream.getvalue()[-15000:])
    return 0 if result.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
