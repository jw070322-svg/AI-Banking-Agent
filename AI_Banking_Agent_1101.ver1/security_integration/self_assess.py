"""One command: test first, publish only on success."""
from pathlib import Path
import subprocess,sys,json
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
def main():
    report=ROOT/'reports/g01-d01-fix/generation-status.json'
    report.parent.mkdir(parents=True,exist_ok=True)
    state={'started_at':datetime.now(timezone.utc).isoformat(),'status':'running'}
    report.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    for module in ('security_integration.verify','security_integration.deliver'):
        result=subprocess.run([sys.executable,'-X','utf8','-B','-m',module],cwd=ROOT)
        if result.returncode:
            state.update(status='failed',failed_step=module,completed_at=datetime.now(timezone.utc).isoformat())
            report.write_text(json.dumps(state,ensure_ascii=False,indent=2))
            print('本次生成失败；未发布新的通过报告。请查看 reports/security-integration-1101/http-tests.txt；已有报告仅代表此前测试。')
            return result.returncode
    state.update(status='passed',completed_at=datetime.now(timezone.utc).isoformat())
    report.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    print('测试及报告生成完成：'+str(ROOT/'安全自评报告_1101.html'))
    return 0
if __name__=='__main__':raise SystemExit(main())
