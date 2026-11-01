"""End-to-end local demo verification; no real transactions or external search."""
from pathlib import Path
from urllib.request import Request, build_opener, HTTPCookieProcessor, ProxyHandler
from urllib.error import HTTPError
from uuid import uuid4
from datetime import datetime, timezone
import json

base='http://127.0.0.1:8795'
client=build_opener(ProxyHandler({}),HTTPCookieProcessor())
def call(path,body=None):
    headers={'Content-Type':'application/json','Idempotency-Key':uuid4().hex}
    req=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    with client.open(req,timeout=30) as response: return json.load(response)

call('/api/session',{})
before=call('/api/snapshot')['data']['state']
status=call('/api/market/status')['data']
market=call('/api/market/context')['data']
unapproved=call('/api/external/search',{'question':'什么是久期'})
unauthorized=call('/api/market/recommend',{})
call('/api/rpc',{'method':'authorize','args':[{'read':True,'trade':False,'subscriptions':False}]})
call('/api/profile',{'risk_tolerance':4,'risk_capacity':4})
recommendation=call('/api/market/recommend',{})
after=call('/api/snapshot')['data']['state']
try:
    call('/api/market/import',{'filename':'x.xlsx','content_base64':'eA=='})
    removed=False
except HTTPError as e:
    removed=e.code==404
report={
    'at':datetime.now(timezone.utc).isoformat(),
    'dataset':{k:status[k] for k in ('filename','sha256','product_count','price_rows','index_count','macro_rows','start_date','end_date')},
    'market_indices_displayed':len(market['indices']),
    'product_nav_series_displayed':len(market['product_observations']),
    'unapproved_public_search_blocked':unapproved.get('error',{}).get('code')=='SEARCH_APPROVAL_REQUIRED',
    'unapproved_account_read_blocked':unauthorized.get('error',{}).get('code')=='SCOPE_DENIED',
    'upload_route_removed':removed,
    'recommendation_succeeded':recommendation.get('error') is None,
    'candidate_count':len((recommendation.get('data') or {}).get('ranked',[])),
    'excluded_count':len((recommendation.get('data') or {}).get('excluded',[])),
    'ledger_unchanged':all(before[k]==after[k] for k in ('available','positions','transactions')),
    'paid_api_calls':0,
}
report['passed']=all([report['dataset']['product_count']==35,report['dataset']['price_rows']==13361,
    report['market_indices_displayed']==9,report['product_nav_series_displayed']==35,report['unapproved_public_search_blocked'],
    report['unapproved_account_read_blocked'],report['upload_route_removed'],
    report['recommendation_succeeded'],report['excluded_count']==35,report['ledger_unchanged']])
(Path(__file__).resolve().parents[1]/'reports/wind-live-1027-ver3.json').write_text(
    json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['passed'] else 1)
