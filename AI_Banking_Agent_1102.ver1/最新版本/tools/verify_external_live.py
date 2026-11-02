from pathlib import Path
from urllib.request import Request,build_opener,HTTPCookieProcessor,ProxyHandler
from uuid import uuid4
from datetime import datetime,timezone
import json,time,sys

port=int(sys.argv[1]) if len(sys.argv)>1 else 8793
if not 1024<=port<=65535: raise ValueError('invalid local port')
base=f'http://127.0.0.1:{port}'
client=build_opener(ProxyHandler({}),HTTPCookieProcessor())
def call(path,body=None,key=None):
    headers={'Content-Type':'application/json','Idempotency-Key':key or uuid4().hex}
    req=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    with client.open(req,timeout=65) as response: data=json.load(response)
    assert data.get('error') is None,data.get('error')
    return data['data']
call('/api/session',{})
before=call('/api/snapshot')['state']
probe=call('/api/external/probe',{})
key=uuid4().hex;start=time.monotonic()
answer=call('/api/knowledge',{'question':'什么是辛普森悖论'},key)
again=call('/api/knowledge',{'question':'什么是辛普森悖论'},key)
after=call('/api/snapshot')['state']
links=call('/api/local-life/links',{'city':'上海','category':'蛋糕'})
report={'at':datetime.now(timezone.utc).isoformat(),'probe':probe,'answer':answer,
        'replay_equal':answer==again,'ledger_unchanged':before==after,'official_links':links,
        'elapsed_seconds':round(time.monotonic()-start,2),'paid_api_calls':0}
expected_notice='本地 AI 已响应，但没有可核验的正文来源，暂不展示未经核实的解释。可主动选择百度搜索或补充正式资料。'
report['ungrounded_output_suppressed']=(answer.get('status')=='needs_evidence'
    and answer.get('model_response_received') is True
    and answer.get('answer')==expected_notice
    and answer.get('citations')==[] and answer.get('evidence')==[] and answer.get('external_data_sent') is False)
report['passed']=all((report['replay_equal'],report['ledger_unchanged'],report['ungrounded_output_suppressed'],
    answer.get('generation_mode')=='llama_cpp',probe['llama_cpp']['status']=='ready'))
(Path(__file__).resolve().parents[1]/'reports/external-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['passed'] else 1)
