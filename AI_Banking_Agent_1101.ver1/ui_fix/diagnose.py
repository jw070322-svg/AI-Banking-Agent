"""Read-only source checks and offline runtime tests, separate from old evidence."""
from pathlib import Path
import hashlib
import importlib
import io
import json
import os
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/ui-cache-1030'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def inventory():
    baseline=json.loads((ROOT/'reports/1029-preservation-baseline.json').read_text(encoding='utf-8'))
    missing=[]; mismatches=[]; cache=[]
    required=dict(baseline['baseline'])
    for item in baseline['incoming']:
        target=ROOT/item['target']
        if target.suffix!='.pyc':
            required[item['target']]=item['sha256'];continue
        stem=target.name.split('.cpython-')[0]
        # The delivered cache files were flattened; tool sources were restored
        # under tool_calling/tools. Do not assume the cache's directory is its
        # actual Python package, nor execute cache contents to discover it.
        candidates=[ROOT/x['target'] for x in baseline['incoming']
                    if Path(x['target']).name==stem+'.py' and Path(x['target']).suffix=='.py'
                    and str(Path(x['target']).parent).startswith(str(Path(item['target']).parent))]
        origins=[]
        for source in candidates:
            module='.'.join(source.relative_to(ROOT).with_suffix('').parts)
            if module.endswith('.__init__'):module=module[:-9]
            imported=importlib.import_module(module)
            origin=Path(imported.__file__).resolve()
            origins.append({'source':str(source.relative_to(ROOT)),'origin':str(origin),
                            'source_loaded':origin==source.resolve()})
        cache.append({**item,'present':target.exists(),
            'original_input_hash_matches':sha(Path(item['source']))==item['sha256'],
            'source_candidates':origins,'loaded_from_source':bool(origins) and all(x['source_loaded'] for x in origins)})
    for path,digest in required.items():
        value=sha(ROOT/path)
        if value is None:missing.append(path)
        elif value!=digest:mismatches.append(path)
    timeline={}
    for name in ['AI_Banking_Agent_1029.ver1','AI_Banking_Agent_1029.ver2','AI_Banking_Agent_1029_rag_review','AI_Banking_Agent_1030.ver1']:
        folder=ROOT.parent/name
        timeline[name]={'folder_exists':folder.exists(),'original_cache_files_present':sum((folder/c['target']).is_file() for c in cache)}
    return {'required_files_checked':len(required),'required_missing':missing,'required_hash_mismatches':mismatches,
            'cache_artifacts':cache,'version_timeline':timeline,
            'runtime_source_integrity_passed':not missing and not mismatches and all(c['loaded_from_source'] for c in cache),
            'legacy_artifact_preservation_passed':all(c['present'] for c in cache)}


def main():
    REPORT.mkdir(parents=True,exist_ok=True)
    before=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*.pyc')]
    assert sys.dont_write_bytecode, 'Run with python -B to verify source-only behavior'
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    data={'python':sys.version,'dont_write_bytecode':sys.dont_write_bytecode,'caches_before':before,'inventory':inventory()}
    from start import prepare_node
    node=prepare_node()
    from review_additions import test_review,test_phase2,evaluate
    from relay_additions import test_boundaries
    from relay_additions.runtime import RelayService
    from ui_fix.server import make_server
    suites=[('legacy-full',unittest.defaultTestLoader.discover(str(ROOT/'tests'))),
            ('current-http',unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in (test_review,test_phase2,test_boundaries)))]
    results={}
    for name,suite in suites:
        stream=io.StringIO()
        with patch('first_agent.external_services.request',return_value={'status':'unavailable','reason':'offline_diagnostic'}), \
             patch.object(evaluate,'REPORT',REPORT),patch.object(test_review,'ReviewService',RelayService), \
             patch.object(test_review,'make_server',make_server),patch.object(test_phase2,'ReviewService',RelayService), \
             patch.object(test_boundaries,'make_server',make_server):
            result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
        (REPORT/(name+'.txt')).write_text(stream.getvalue(),encoding='utf-8')
        results[name]={'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
                      'error_tests':[t.id() for t,_ in result.errors],'passed':result.wasSuccessful()}
        print(name,results[name],flush=True)
    frontend=[]
    for p in [*sorted((ROOT/'tests_frontend').glob('*.cjs')),ROOT/'review_additions/test_frontend.cjs',ROOT/'relay_additions/test_frontend.cjs']:
        run=subprocess.run([node,str(p)],capture_output=True,text=True,encoding='utf-8')
        frontend.append({'path':str(p.relative_to(ROOT)),'exit_code':run.returncode,'stdout':run.stdout,'stderr':run.stderr})
    data.update(tests=results,frontend=frontend,caches_after=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*.pyc')])
    # Keep the original failing test visible; separate it from runtime health.
    expected=['test_tools_security_1029.QuotaAndPreservationTests.test_preservation']
    legacy=results['legacy-full']
    data['runtime_checks_passed']=(data['inventory']['runtime_source_integrity_passed'] and not before and not data['caches_after']
        and legacy['failures']==0 and legacy['error_tests']==expected and results['current-http']['passed']
        and all(x['exit_code']==0 for x in frontend))
    (REPORT/'cache-diagnostic.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'runtime_checks_passed':data['runtime_checks_passed'],'old_artifact_check':'still_fails_missing_cache','caches_before':len(before),'caches_after':len(data['caches_after'])}))
    return 0 if data['runtime_checks_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
