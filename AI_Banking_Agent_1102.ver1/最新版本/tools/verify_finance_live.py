from urllib.request import Request,build_opener,HTTPCookieProcessor,ProxyHandler
from pathlib import Path
from uuid import uuid4
from datetime import datetime,timezone
import json

client=build_opener(ProxyHandler({}),HTTPCookieProcessor());base='http://127.0.0.1:8796'
def call(path,body=None):
    req=Request(base+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
                headers={'Content-Type':'application/json','Idempotency-Key':uuid4().hex})
    with client.open(req,timeout=60) as res:out=json.load(res)
    if out.get('error'):raise RuntimeError(out['error'])
    return out['data']
call('/api/session',{});before=call('/api/snapshot')['state']
queries=['什么是债券基金？','基金净值估算是什么？','借记卡和信用卡的区别','夏普率是什么？']
answers=[]
for q in queries:
    r=call('/api/rpc',{'method':'assistant','args':[q]})
    a=r['results'][0]['result'] if r.get('route')=='customer-result' else {}
    answers.append({'question':q,'terms':a.get('matched_terms',[]),'grounded':a.get('status')=='grounded',
                    'has_reference':bool(a.get('citations'))})
links=call('/api/local-life/links',{'city':'上海','category':'蛋糕'})
after=call('/api/snapshot')['state']
report={'at':datetime.now(timezone.utc).isoformat(),'answers':answers,
        'meituan_url':links['items'][0]['url'],'ledger_unchanged':before['available']==after['available'] and before['positions']==after['positions'],
        'no_paid_api':True}
report['passed']=all(x['grounded'] and x['has_reference'] and x['terms'] for x in answers) and report['meituan_url']=='https://www.meituan.com/' and report['ledger_unchanged']
(Path(__file__).resolve().parents[1]/'reports/finance-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['passed'] else 1)
