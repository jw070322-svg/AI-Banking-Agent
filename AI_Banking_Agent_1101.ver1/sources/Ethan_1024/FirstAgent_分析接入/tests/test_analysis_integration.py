"""Integration tests: analysis toolkit over the persisted demo ledger."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json, threading, unittest
from unittest.mock import patch
from urllib.request import Request, build_opener, HTTPCookieProcessor

from first_agent.analysis_bridge import analysis_status, session_to_scenario
from first_agent.server import make_server
from first_agent.service import AgentService

class AnalysisBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.service=AgentService(Path(self.temp.name)/'analysis.sqlite3',clock=lambda:1800000000.0)
        self.sid=self.service.create_session();self.n=0
    def call(self,action,args=None):
        self.n+=1
        return self.service.call(self.sid,action,args,f'analysis-key-{self.n}')
    def ready(self):
        return self.call('rpc',{'method':'authorize','args':[{'read':True,'subscriptions':True,'trade':False}]})
    def analysis(self,tool,args=None):
        return self.call('analysis',{'tool':tool,'args':args or {}})

    def state(self):
        return self.service.call(self.sid,'snapshot',{}).get('data',{}).get('state',{})

    def test_analysis_module_is_available(self):
        status=analysis_status()
        self.assertTrue(status['available'],status)
        self.assertIn('analysis.pipeline',status['tools'])

    def test_analysis_requires_read_consent(self):
        response=self.analysis('bills.summary')
        self.assertEqual(response['error']['code'],'SCOPE_DENIED')

    def test_session_to_scenario_contract(self):
        scenario=session_to_scenario(self.state())
        self.assertEqual(scenario['currency'],'CNY')
        self.assertFalse(scenario['ledger_modified'])
        self.assertEqual(scenario['accounts'][0]['balance_minor'],3864000)
        categories={t['category'] for t in scenario['transactions']}
        self.assertTrue({'工资','居住','餐饮','购物','交通','订阅'} <= categories)
        for transaction in scenario['transactions']:
            self.assertIsInstance(transaction['amount_minor'],int)
            self.assertIn(transaction['status'],{'booked','pending','rejected','failed'})
        subscriptions={s['merchant']:s for s in scenario['subscriptions']}
        self.assertEqual(subscriptions['映像会员']['amount_minor'],9600)
        self.assertEqual(subscriptions['映像会员']['next_charge_date'],'2026-11-03')
        self.assertNotIn('customer_phone',json.dumps(scenario))

    def test_bills_summary_matches_ledger(self):
        self.ready();before=self.state()
        response=self.analysis('bills.summary',{'month':'2026-10'})
        self.assertIsNone(response['error'],response)
        report=response['data']['result']
        self.assertEqual(report['month'],'2026-10')
        self.assertEqual(report['income_minor'],2850000)
        self.assertEqual(report['spending_minor'],1286000)
        self.assertEqual(report['net_minor'],1564000)
        self.assertFalse(response['data']['ledger_modified'])
        self.assertEqual(self.state(),before)

    def test_categories_and_anomalies(self):
        self.ready()
        categories=self.analysis('bills.categories',{'month':'2026-10'})['data']['result']
        by_name={row['category']:row['spending_minor'] for row in categories}
        self.assertEqual(by_name['居住'],600000)
        self.assertEqual(by_name['订阅'],16900)

        findings=self.analysis('anomalies.detect')['data']['result']
        types={item['insight_type'] for item in findings}
        self.assertIn('salary_detected',types)
        self.assertEqual(sum(1 for item in findings if item['insight_type']=='subscription_renewal'),3)
        self.assertNotIn('unusual_spending',types)
        self.assertEqual(len(findings),4)

    def test_cashflow_and_liquidity(self):
        self.ready()
        projection=self.analysis('cashflow.project',{'days':30})['data']['result']
        self.assertEqual(projection['starting_balance_minor'],3864000)
        self.assertEqual(projection['scheduled_outflow_minor'],16900)
        self.assertEqual(projection['expected_income_minor'],2850000)
        self.assertEqual(projection['lowest_balance_minor'],3847100)
        self.assertEqual(projection['ending_balance_minor'],6697100)
        liquidity=self.analysis('liquidity.available',{'days':30})['data']['result']
        self.assertEqual(liquidity['locked_amount_minor'],0)
        self.assertEqual(liquidity['safe_to_spend_now_minor'],3847100)

    def test_budget_advice(self):
        self.ready()
        advice=self.analysis('budget.advice',{'days':30})['data']['result']
        self.assertEqual(advice['monthly_income_minor'],2850000)
        self.assertEqual(advice['monthly_surplus_minor'],1564000)
        self.assertEqual(advice['savings']['safe_monthly_minor'],1564000)
        self.assertEqual(advice['investment']['safe_monthly_minor'],0)
        self.assertEqual(advice['recommended_action'],'build_emergency_fund')
        self.assertFalse(advice['ledger_modified'])

    def test_recommendation_uses_analysis_budget(self):
        self.ready()
        result=self.call('recommend',{})['data']
        basis=result['budget_basis']
        self.assertEqual(basis['configured_minor'],364000)
        self.assertEqual(basis['engine_capacity_minor'],364000)
        self.assertEqual(basis['analysis_headroom_minor'],0)
        self.assertEqual(basis['applied_minor'],364000)
        self.assertEqual(basis['source'],'engine_capacity')
        self.assertTrue(any('应急金' in item for item in result['warnings']))
        self.assertTrue(result['recommendations'])

    def test_recommendation_uses_positive_analysis_headroom(self):
        self.ready()
        advice={'investment':{'headroom_minor':10000}}
        with patch('first_agent.service.run_analysis_tool',return_value={'result':advice}):
            result=self.call('recommend',{})['data']
        self.assertEqual(result['budget_basis']['analysis_headroom_minor'],10000)
        self.assertEqual(result['budget_basis']['applied_minor'],10000)
        self.assertEqual(result['budget_basis']['source'],'analysis')

    def test_recommendation_without_read_consent_falls_back(self):
        result=self.call('recommend',{})['data']
        self.assertIsNone(result['budget_basis']['analysis_headroom_minor'])
        self.assertEqual(result['budget_basis']['source'],'engine_capacity')

    def test_pipeline_returns_full_chain(self):
        self.ready()
        result=self.analysis('analysis.pipeline',{'days':30})['data']['result']
        self.assertEqual(result['scenario']['scenario_type'],'SESSION')
        self.assertEqual(result['period']['month'],'2026-10')
        self.assertGreaterEqual(len(result['findings']),4)
        self.assertEqual(result['summary']['income_minor'],2850000)
        self.assertNotIn('evaluation',result)

    def test_analysis_cannot_generate_scenarios(self):
        self.ready()
        response=self.analysis('scenario.generate',{'prompt':'普通用户'})
        self.assertEqual(response['error']['code'],'TOOL_NOT_REGISTERED')

    def test_scenario_generation_does_not_touch_ledger(self):
        before=self.state()
        response=self.call('scenario.generate',{'prompt':'普通用户','scenario_type':'A','seed':1,'reference_date':'2026-10-23'})
        if response.get('error'):
            if response['error']['code']=='ENVIRONMENT_UNAVAILABLE':self.skipTest('environment agent missing')
            self.fail(response['error'])
        self.assertEqual(response['data']['scenario']['scenario_type'],'A')
        self.assertFalse(response['data']['ledger_modified'])
        self.assertEqual(self.state(),before)

class AnalysisHttpTests(unittest.TestCase):
    def test_http_analysis_endpoint_is_read_only(self):
        with TemporaryDirectory() as temp:
            service=AgentService(Path(temp)/'http-analysis.sqlite3');server=make_server(service,port=0)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            try:
                base=f'http://127.0.0.1:{server.server_port}';client=build_opener(HTTPCookieProcessor())
                def post(path,data,**headers):
                    req=Request(base+path,json.dumps(data).encode(),{'Content-Type':'application/json','Idempotency-Key':str(id(data)),**headers})
                    return json.loads(client.open(req).read())
                post('/api/session',{})
                post('/api/rpc',{'method':'authorize','args':[{'read':True,'subscriptions':True,'trade':False}]})
                before=json.loads(client.open(base+'/api/accounts/overview').read())['data']
                response=post('/api/analysis',{'tool':'bills.summary','args':{'month':'2026-10'}})
                self.assertIsNone(response['error'],response)
                self.assertEqual(response['data']['result']['spending_minor'],1286000)
                health=json.loads(client.open(base+'/api/health').read())['data']
                self.assertTrue(health['analysis']['available'])
                after=json.loads(client.open(base+'/api/accounts/overview').read())['data']
                self.assertEqual(before,after)
            finally:server.shutdown();server.server_close();worker.join(3)

if __name__=='__main__':unittest.main()
