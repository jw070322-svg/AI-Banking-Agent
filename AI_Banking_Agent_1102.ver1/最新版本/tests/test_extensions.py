import base64, copy, io, json, math, statistics, threading, unittest, zipfile
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError
from first_agent.service import AgentService
from first_agent.server import make_server
from first_agent import calendar_provider as cal
from first_agent.market_data import import_workbook, metrics, recommend, market_context, MarketError

ROOT=Path(__file__).resolve().parents[1]
def workbook(name='wind_sample.xlsx'): return base64.b64encode((ROOT/'data'/name).read_bytes()).decode()

class MarketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.data=import_workbook(workbook())
    def test_real_xlsx_rows_and_template(self):
        self.assertEqual(len(self.data['products']),5)
        self.assertEqual(sum(map(len,self.data['prices'].values())),1325)
        self.assertTrue(self.data['metadata']['synthetic'])
        with self.assertRaises(MarketError): import_workbook(workbook('wind_template.xlsx'))
    def test_invalid_zip_and_formula_rejected(self):
        with self.assertRaises(MarketError): import_workbook('eHl6')
        src=zipfile.ZipFile(io.BytesIO(base64.b64decode(workbook())));out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            for name in src.namelist():
                data=src.read(name)
                if name.endswith('.xml') and name.startswith('xl/worksheets/'):
                    import xml.etree.ElementTree as ET
                    tree=ET.fromstring(data);ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                    cell=next(tree.iter(ns+'c'),None)
                    if cell is not None: ET.SubElement(cell,ns+'f').text='1+1'
                    data=ET.tostring(tree)
                z.writestr(name,data)
        with self.assertRaises(MarketError): import_workbook(base64.b64encode(out.getvalue()).decode())
    def test_math_independently_computed(self):
        values={};v=100;d=date(2026,1,1)
        for i in range(65):
            v*=1+(.001 if i%2 else -.0004);values[(d+timedelta(days=i)).isoformat()]=v
        rf={day:.01 for day in values};m=metrics(values,rf)
        vs=list(values.values());r=[b/a-1 for a,b in zip(vs,vs[1:])]
        self.assertAlmostEqual(m['annualized_return'],(vs[-1]/vs[0])**(365/64)-1)
        self.assertAlmostEqual(m['sharpe'],(statistics.mean(r)-((1.01)**(1/252)-1))/statistics.stdev(r)*math.sqrt(252))
        self.assertAlmostEqual(m['max_drawdown'],.0004)
        zero=metrics({k:100 for k in values},rf);self.assertIsNone(zero['sharpe'])
    def test_future_data_does_not_change_results(self):
        p=dict(risk_tolerance=5,risk_capacity=5,amount_minor=200000,horizon_days=180)
        before=recommend(self.data,p,'2026-10-26');other=copy.deepcopy(self.data)
        for series in other['prices'].values():series['2027-01-01']=999
        other['macro'].append(dict(indicator='PMI',date='2026-10-01',available_date='2026-11-01',value=10,unit='指数',source='synthetic'))
        self.assertEqual(before,recommend(other,p,'2026-10-26'))
    def test_risk_money_term_and_stale_filters(self):
        p=dict(risk_tolerance=4,risk_capacity=4,amount_minor=200000,horizon_days=180)
        r=recommend(self.data,p,'2026-10-26');self.assertEqual(r['effective_risk_cap'],2)
        self.assertTrue(r['ranked']);self.assertTrue(all(x['risk_level']<=2 for x in r['ranked']))
        self.assertEqual(recommend(self.data,{**p,'amount_minor':0},'2026-10-26')['ranked'],[])
        self.assertEqual(recommend(self.data,p,'2027-01-01')['ranked'],[])
        self.assertTrue(any('到账' in reason for x in r['excluded'] for reason in x['reasons']))
    def test_macro_and_sector_influence(self):
        d=copy.deepcopy(self.data);d['indices']={};d['macro']=[dict(indicator='PMI',date='2026-09-30',available_date='2026-10-01',value=48,unit='指数',source='synthetic')]
        self.assertTrue(market_context(d,'2026-10-26')['risk_off'])
        d['macro']=[];sector=d['products']['SYN-TECH']['sector'];d['indices']={'TEST':dict(code='TEST',name='Sector',sector=sector,source='synthetic',values={(date(2026,10,1)+timedelta(days=i)).isoformat():100-i for i in range(23)})}
        r=recommend(d,dict(risk_tolerance=5,risk_capacity=5,amount_minor=200000,horizon_days=180),'2026-10-26')
        self.assertTrue(any('板块' in reason for x in r['excluded'] if x['code']=='SYN-TECH' for reason in x['reasons']))
    def test_bundled_wind_limits_are_not_assumed_away(self):
        from first_agent.local_wind import load_local_wind
        d,error=load_local_wind();self.assertIsNone(error)
        self.assertEqual((len(d['products']),sum(map(len,d['prices'].values())),len(d['indices']),len(d['macro'])),(35,13361,9,67))
        observed=market_context(d,'2026-10-27')['product_observations']
        fund=next(x for x in observed if x['code']=='485119.OF')
        self.assertEqual(fund['latest_nav'],d['prices']['485119.OF'][fund['as_of']]);self.assertEqual(len(observed),35)
        result=recommend(d,dict(risk_tolerance=5,risk_capacity=5,amount_minor=20000000,horizon_days=180),'2026-10-27')
        etf=next(x for x in result['excluded'] if x['code']=='510300.SH')
        self.assertTrue(any('份额' in reason for reason in etf['reasons']))
        bank=next(x for x in result['excluded'] if x['code']=='GL24651.LC')
        self.assertTrue(any('单位净值' in reason for reason in bank['reasons']))
        self.assertFalse(d['metadata']['macro_publication_dates_verified'])
    def test_extreme_growth_excluded_without_overflow(self):
        d=copy.deepcopy(self.data)
        d['prices']['SYN-CASH']={(date(2026,8,24)+timedelta(days=i)).isoformat():1e-8*1.95**i*(1+.001*(i%2)) for i in range(61)}
        d['risk_free']={key:.01 for key in d['prices']['SYN-CASH']}
        r=recommend(d,dict(risk_tolerance=1,risk_capacity=1,amount_minor=200000,horizon_days=1080),'2026-10-26')
        self.assertTrue(any('有效范围' in reason for x in r['excluded'] if x['code']=='SYN-CASH' for reason in x['reasons']))

class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.service=AgentService(Path(self.temp.name)/'test.sqlite3');self.sid=self.service.create_session();self.n=0
        self.today_patch=patch('first_agent.calendar_provider.today',return_value='2026-10-26');self.today_patch.start();self.addCleanup(self.today_patch.stop)
        self.rpc('authorize',{'read':True,'trade':True,'subscriptions':True})
    def call(self,action,args=None,key=None):
        self.n+=1;return self.service.call(self.sid,action,args,key or str(self.n))
    def ok(self,action,args=None,key=None):
        r=self.call(action,args,key);self.assertIsNone(r['error'],r);return r['data']
    def rpc(self,method,*args):return self.ok('rpc',{'method':method,'args':list(args)})
    def state(self):return self.ok('snapshot')['state']
    def event(self,dt='2026-10-29'):return self.ok('calendar.save',{'title':'生日','date':dt,'city':'上海'})['event']['id']
    def test_week_window_and_no_auto_reservation(self):
        self.event('2026-10-25');self.event('2026-10-26');self.event('2026-11-01');self.event('2026-11-02')
        v=self.ok('calendar.list');self.assertEqual(len(v['reminders']),2);self.assertEqual(v['reserved_minor'],0)
    def test_reserve_replace_replay_release_and_conservation(self):
        event=self.event();before=self.ok('snapshot');args={'event_id':event,'amount_minor':100000}
        a=self.ok('calendar.reserve',args,'same-reserve');self.ok('calendar.reserve',args,'same-reserve')
        self.assertEqual(a['capacity_minor'],before['capacity']-100000)
        self.ok('calendar.reserve',{**args,'amount_minor':120000})
        self.assertEqual(self.ok('calendar.list')['reserved_minor'],120000)
        self.assertEqual(self.state()['available'],before['state']['available'])
        self.assertEqual(self.ok('calendar.list')['reminders'],[])
        self.ok('calendar.release',{'event_id':event});self.assertEqual(self.ok('snapshot')['capacity'],before['capacity'])
    def test_invalid_reserve_rollback_and_pending_invalidated(self):
        event=self.event();before=self.state()
        for amount in (True,-1,0,1.5,999999999):
            self.assertIsNotNone(self.call('calendar.reserve',{'event_id':event,'amount_minor':amount})['error'])
        self.assertEqual(self.state(),before)
        op=self.rpc('propose','purchase');self.ok('calendar.reserve',{'event_id':event,'amount_minor':100})
        self.assertEqual(next(x for x in self.state()['operations'] if x['id']==op['id'])['status'],'invalidated')
    def test_nlp_grounded_and_does_not_execute(self):
        for text in ('转账名录里到底有哪些人','什么是夏普率？','复利是什么意思？'):
            result=self.rpc('assistant',text);self.assertEqual(result['route'],'customer-result')
        for text in ('打开网站连接','网站与免费 AI','检查 llama.cpp','打开外部 AI'):
            result=self.rpc('assistant',text);self.assertEqual(result['route'],'connections')
        self.assertEqual(self.state()['operations'],[])
    def test_cashflow_reserves_once_and_uses_personal_schedule(self):
        def project():return self.ok('analysis',{'tool':'cashflow.project','args':{'days':30}})['result']
        before=project();eid=self.event()
        self.ok('calendar.reserve',{'event_id':eid,'amount_minor':100000})
        after=project();self.assertEqual(after['scheduled_outflow_minor']-before['scheduled_outflow_minor'],100000)
        self.assertEqual(before['ending_balance_minor']-after['ending_balance_minor'],100000)
        liquidity=self.ok('analysis',{'tool':'liquidity.available','args':{'days':30}})['result']
        self.assertEqual(liquidity['locked_amount_minor'],100000);self.assertEqual(liquidity['reserved_remaining_minor'],0)
        self.assertEqual(liquidity['planned_activity_minor'],100000)
        self.ok('profile.update',{'monthly_income_minor':2000000,'monthly_expense_minor':500000,'salary_day':15,'expense_day':5})
        personal=project();self.assertEqual(personal['expected_income_minor'],2000000);self.assertEqual(personal['scheduled_outflow_minor'],600000)
        self.assertEqual(self.state()['available'],3864000)
    def test_import_atomic_private_and_reserve_affects_recommendation(self):
        status=self.ok('market.status');self.assertEqual(status['product_count'],35);self.assertEqual(status['price_rows'],13361)
        self.assertNotIn('market_data',self.state())
        self.service.market_data=import_workbook(workbook())
        self.ok('profile.update',{'risk_tolerance':4,'risk_capacity':4})
        r=self.ok('market.recommend');self.ok('calendar.reserve',{'event_id':self.event(),'amount_minor':100000})
        after=self.ok('market.recommend');self.assertEqual(r['profile']['amount_minor']-after['profile']['amount_minor'],100000)
        self.assertTrue(after['ranked']);self.assertLess(after['ranked'][0]['scenario_gain_minor'],r['ranked'][0]['scenario_gain_minor'])
        self.rpc('setProfile','expired');self.assertIsNotNone(self.call('market.recommend')['error'])
    def test_page_open_reads_google_each_time_and_failure_not_reminded(self):
        e=[dict(id='google:1',title='生日',date='2026-10-28',special=True,source='google')]
        with patch.object(cal,'fetch_google',return_value=(e,{'status':'connected'})) as f:
            self.ok('page.open');self.ok('page.open');self.assertEqual(f.call_count,2)
        with patch.object(cal,'fetch_google',return_value=(None,{'status':'sync_failed'})):
            self.assertEqual(self.ok('page.open')['calendar']['reminders'],[])
        self.assertEqual(self.ok('calendar.list')['reminders'],[])
    def test_audit_eight_fields_and_no_uploaded_bytes(self):
        self.ok('market.status')
        records=self.ok('audit.export')['records'];fields={'user_id','intent','tool','input','output','risk_check','approval','timestamp'}
        self.assertTrue(all(set(r)==fields for r in records));self.assertNotIn('content_base64',json.dumps(records))
    def test_google_parse_timezone_pagination_and_readonly(self):
        class Response:
            def __init__(self,obj):self.data=json.dumps(obj).encode()
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,*a):return self.data
        one={'items':[{'id':'1','summary':'birthday','start':{'dateTime':'2026-10-25T18:00:00Z'}}],'nextPageToken':'next'}
        two={'items':[{'id':'2','status':'cancelled','start':{'date':'2026-10-26'}}]}
        with patch.dict('os.environ',{'BANKING_GOOGLE_ACCESS_TOKEN':'test-placeholder'}),patch.object(cal,'urlopen',side_effect=[Response(one),Response(two)]) as f:
            events,status=cal.fetch_google('2026-10-26');self.assertEqual(status['status'],'connected');self.assertEqual(events[0]['date'],'2026-10-26');self.assertTrue(events[0]['special']);self.assertEqual(len(events),1)
            self.assertTrue(all(c.args[0].get_method()=='GET' for c in f.call_args_list));self.assertIn('pageToken=next',f.call_args_list[1].args[0].full_url)
    def test_http_xlsx_upload_and_snapshot(self):
        server=make_server(self.service,port=0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        client=build_opener(HTTPCookieProcessor());base='http://127.0.0.1:'+str(server.server_port)
        def post(path,args):
            return json.loads(client.open(Request(base+path,data=json.dumps(args).encode(),headers={'Content-Type':'application/json','Idempotency-Key':path})).read())
        try:
            post('/api/session',{})
            with self.assertRaises(HTTPError) as error: post('/api/market/import',{'filename':'x.xlsx','content_base64':'eA=='})
            self.assertEqual(error.exception.code,404)
            state=json.loads(client.open(base+'/api/snapshot').read())['data']['state'];self.assertEqual(state['market_status']['product_count'],35);self.assertNotIn('market_data',state)
        finally:server.shutdown();server.server_close();thread.join()
