"""Recheck changed composition only; retain earlier full regression evidence."""
import io
import json
import unittest
from unittest.mock import patch
from relay_additions.verify import ROOT, REPORT
from relay_additions.runtime import RelayService, make_server
from review_additions import test_review, test_phase2, evaluate


def main():
    summary={}
    for name,suite in [('relay-final',unittest.defaultTestLoader.loadTestsFromName('relay_additions.test_boundaries')),
        ('assembled-final',unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in (test_review,test_phase2)))]:
        stream=io.StringIO()
        with patch.object(test_review,'ReviewService',RelayService),patch.object(test_review,'make_server',make_server), \
             patch.object(test_phase2,'ReviewService',RelayService),patch.object(evaluate,'REPORT',REPORT), \
             patch('first_agent.external_services.request',return_value={'status':'unavailable','reason':'offline_verification'}):
            result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
        (REPORT/(name+'.txt')).write_text(stream.getvalue(),encoding='utf-8')
        summary[name]={'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()}
        print(name,summary[name],flush=True)
    with patch.object(evaluate,'REPORT',REPORT),patch.object(evaluate,'ReviewService',RelayService):
        evaluate.run()
    (REPORT/'final.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return 0 if all(v['passed'] for v in summary.values()) else 1


if __name__=='__main__':raise SystemExit(main())
