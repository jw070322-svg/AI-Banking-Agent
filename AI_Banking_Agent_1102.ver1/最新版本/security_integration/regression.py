"""Run inherited regression, restore generated inherited evidence byte-for-byte."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest,io,json,subprocess,shutil
from datetime import datetime,timezone
from .evidence import source_fingerprint
from urllib.error import URLError
from unittest.mock import patch
from start import prepare_node

def main():
    started_at=datetime.now(timezone.utc).isoformat()
    root=Path(__file__).resolve().parents[1];out=root/'reports/security-integration-1101'
    hashes=json.loads((out/'input-hashes.json').read_text())
    node=prepare_node()
    # Some inherited tests rewrite their historical report files. Restore their original bytes.
    with TemporaryDirectory() as folder:
        saved=Path(folder)
        for rel in hashes:
            f=root/rel
            if f.is_file():
                target=saved/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,target)
        stream=io.StringIO()
        try:
            with patch('first_agent.external_services.build_opener') as opener:
                opener.return_value.open.side_effect=URLError('offline_regression')
                result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.discover(str(root/'tests')))
            frontend=[]
            for f in sorted((root/'tests_frontend').glob('*.cjs')):
                run=subprocess.run([node,str(f)],capture_output=True,text=True)
                frontend.append({'file':f.name,'exit_code':run.returncode,'output':run.stdout if run.returncode==0 else run.stderr})
        finally:
            for f in saved.rglob('*'):
                if f.is_file():shutil.copyfile(f,root/f.relative_to(saved))
    (out/'inherited-regression.txt').write_text(stream.getvalue())
    report={'started_at':started_at,'completed_at':datetime.now(timezone.utc).isoformat(),'source_fingerprint':source_fingerprint(root),'backend':{'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()},'frontend':frontend}
    (out/'inherited-regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(report['backend']);print('frontend failures',[r['file'] for r in frontend if r['exit_code']])
    if not result.wasSuccessful():print(stream.getvalue()[-9000:])
    return 0 if result.wasSuccessful() and all(r['exit_code']==0 for r in frontend) else 1
if __name__=='__main__':raise SystemExit(main())
