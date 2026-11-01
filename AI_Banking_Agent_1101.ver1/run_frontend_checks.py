from pathlib import Path
import json,subprocess,sys
from start import prepare_node

def main():
    node=prepare_node();root=Path(__file__).resolve().parent;results=[];failed=False
    for p in sorted((root/'tests_frontend').glob('*.cjs')):
        r=subprocess.run([node,str(p)],capture_output=True,text=True,encoding='utf-8')
        if r.returncode:failed=True;results.append({'file':p.name,'error':r.stderr})
        else:results.append({'file':p.name,**json.loads(r.stdout)})
    for p in ['backend-client.js','journey-workspace.js','customer-view.js','planning-market.js','projection-chart.js','external-services.js']:
        r=subprocess.run([node,'--check',str(root/'web'/p)],capture_output=True,text=True,encoding='utf-8')
        if r.returncode:failed=True;results.append({'file':p,'error':r.stderr})
    result={'passed':not failed,'total':sum(r.get('passed',0) for r in results),'results':results}
    (root/'reports/latest-frontend-tests.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':not failed,'total':result['total'],'errors':[r for r in results if 'error' in r]},ensure_ascii=False))
    return 1 if failed else 0
if __name__=='__main__':sys.exit(main())
