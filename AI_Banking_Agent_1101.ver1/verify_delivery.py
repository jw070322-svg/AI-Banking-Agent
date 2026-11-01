"""Run the current release suites; preserve legacy reports as historical evidence."""
from pathlib import Path
from datetime import datetime, timezone
import json, subprocess, sys
from start import prepare_node
ROOT=Path(__file__).resolve().parent

def main():
    prepare_node()
    checks={}
    commands=[('integration',[sys.executable,'-X','utf8','run_integration_checks.py'],ROOT),
              ('frontend',[sys.executable,'-X','utf8','run_frontend_checks.py'],ROOT),
              ('analysis-module',[sys.executable,'-X','utf8','-m','unittest','discover','-s','tests'],ROOT/'modules'/'主任务_金融分析与量化')]
    for name,command,cwd in commands:
        result=subprocess.run(command,cwd=cwd,text=True,encoding='utf-8',capture_output=True,timeout=300)
        log=ROOT/'reports'/('release-'+name+'.txt');log.write_text(result.stdout+result.stderr,encoding='utf-8')
        checks[name]={'passed':result.returncode==0,'log':str(log.relative_to(ROOT))}
    report={'version':'AI_Banking_Agent_1027.ver2','verified_at':datetime.now(timezone.utc).isoformat(),'checks':checks,'passed':all(c['passed'] for c in checks.values())}
    (ROOT/'reports'/'release-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['passed'] else 1
if __name__=='__main__':sys.exit(main())
