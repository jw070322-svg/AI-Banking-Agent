"""Cross-module regressions, without importing duplicate unittest classes."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.request import Request, build_opener, HTTPCookieProcessor
import json, threading, unittest

import test_integration as base
from first_agent.analysis_bridge import AnalysisError, session_to_scenario, _load_modules
from first_agent.service import AgentService, canonical
from first_agent.server import make_server


class ThirdAgentTests(unittest.TestCase):
    setUp=base.IntegrationTests.setUp
    call=base.IntegrationTests.call
    rpc=base.IntegrationTests.rpc
    preview=base.IntegrationTests.preview
    ready=base.IntegrationTests.ready

    def state(self):
        with self.service.transaction() as db:
            return deepcopy(self.service.load(db,self.sid))

    def analysis(self,tool='data.organize',args=None):
        return self.call('analysis',{'tool':tool,'args':args or {}})

    def test_organizer_all_views_and_ledger_unchanged(self):
        self.ready();before=self.state();reply=self.analysis()
        self.assertIsNone(reply['error'],reply)
        package=reply['data']['result']
        self.assertEqual(set(package['views']),{'analysis','recommendation','cards','display'})
        self.assertEqual(package['views']['display']['available_balance_minor'],before['available'])
        self.assertEqual(len(package['views']['cards']['cards']),2)
        self.assertIn('credit_card_bill',package['views']['cards']['missing'])
        self.assertEqual(self.state(),before)
        public=json.dumps(package)
        for forbidden in ['expected_insights','session_id','13800000001','assertion']:
            # A warning may name the stripped evaluation field, but no such key exists.
            if forbidden=='expected_insights':
                self.assertNotIn('"expected_insights":',public)
            else:self.assertNotIn(forbidden,public)

    def test_read_consent_expiry_and_client_context_rejected(self):
        self.assertEqual(self.analysis()['error']['code'],'SCOPE_DENIED')
        self.ready()
        for args in [{'scenario_file':'secret.json'},{'include_evaluation':True},{'data':{}},{'context':{'configured_amount_minor':999999}}]:
            self.assertEqual(self.analysis(args=args)['error']['code'],'INVALID_ARGUMENT')
        self.now[0]+=86400
        self.assertEqual(self.analysis()['error']['code'],'SCOPE_EXPIRED')

    def test_pending_preview_remains_executable_after_analysis(self):
        self.ready();op=self.preview();before=self.state()
        for name in ['data.organize','analysis.pipeline','budget.advice']:
            self.assertIsNone(self.analysis(name)['error'])
        self.assertEqual(self.state(),before)
        done=self.call('transfer.confirm',{'operation_id':op['id'],'confirmed':True})
        self.assertEqual(done['data']['status'],'succeeded')

    def test_transfer_is_outflow_and_not_consumption(self):
        self.ready();op=self.preview()
        self.call('transfer.confirm',{'operation_id':op['id'],'confirmed':True})
        report=self.analysis('bills.summary',{'month':'2026-10'})['data']['result']
        self.assertEqual(report['spending_minor'],1286000)
        self.assertEqual(report['transfer_out_minor'],80000)
        self.assertEqual(report['available_balance_minor'],3784000)
        scenario=session_to_scenario(self.state());a=scenario['accounts'][0]
        self.assertEqual(a['initial_balance_minor']+sum(t['amount'] for t in scenario['transactions'] if t['status']=='booked'),a['balance_minor'])

    def test_purchase_redemption_types_do_not_become_expense_refund(self):
        state=self.state()
        state['transactions'] += [dict(id='PURCHASE',category='investment',amount=-10000,date='2026-10-19',status='booked'),
                                  dict(id='REDEEM',category='redeem',amount=10000,date='2026-10-19',status='booked')]
        scenario=session_to_scenario(state)
        report=_load_modules()['tools'].call_tool('bills.summary',{'month':'2026-10'},data=scenario)['data']
        self.assertEqual(report['spending_minor'],1286000)
        types={t['transaction_id']:t['transaction_type'] for t in scenario['transactions']}
        self.assertEqual(types['PURCHASE'],'investment_purchase')
        self.assertEqual(types['REDEEM'],'investment_redemption')

    def test_subscription_cancellation_changes_future_not_balance(self):
        self.ready();before=self.state()['available']
        self.rpc('reviewSubscription','video');op=self.rpc('propose','subscription','video')['data']
        self.rpc('execute',op['id'],'success')
        projection=self.analysis('cashflow.project')['data']['result']
        self.assertEqual(projection['scheduled_outflow_minor'],1286000-9600)
        self.assertEqual(self.state()['available'],before)

    def test_cards_projection_uses_persisted_loss_state(self):
        self.rpc('authorize',{'read':True,'trade':True,'subscriptions':True,'cards':True})
        op=self.rpc('propose','card_loss','CARD-DEBIT')['data']
        self.rpc('verify',op['id'],'246810');self.rpc('execute',op['id'],'success')
        cards=self.analysis()['data']['result']['views']['cards']['cards']
        self.assertEqual(cards[0]['status'],'lost')
        self.assertEqual(self.call('transfer.preview',{'amount_minor':100,'beneficiary_name':'张三'})['error']['code'],'CARD_BLOCKED')

    def test_recommendation_real_positive_headroom_matches_organizer(self):
        self.ready()
        with self.service.transaction() as db:
            state=self.service.load(db,self.sid)
            state['available']+=2000000;state['initialTotal']+=2000000
            state['goal'].update(total=state['available'],need=0,emergency=0)
            state['amount']=5000000
            db.execute('UPDATE sessions SET state=? WHERE sid=?',(canonical(state),self.sid))
        before=self.state()
        view=self.analysis()['data']['result']['views']['recommendation']
        reply=self.call('recommend')['data'];basis=reply['budget_basis']
        self.assertGreater(basis['analysis_headroom_minor'],0)
        self.assertLess(basis['analysis_headroom_minor'],5000000)
        self.assertEqual(basis['applied_minor'],view['conditions']['budget_minor'])
        self.assertEqual(basis['source'],'analysis')
        self.assertEqual(view['profile']['budget_cny'],basis['applied_minor']/100)
        self.assertEqual(self.state(),before)

    def test_missing_analysis_falls_back_without_changing_config(self):
        self.ready();before=self.state()
        with patch('first_agent.service.run_analysis_tool',side_effect=AnalysisError('ANALYSIS_UNAVAILABLE','missing')):
            response=self.call('recommend')['data']
        self.assertEqual(response['budget_basis']['applied_minor'],364000)
        self.assertEqual(response['budget_basis']['analysis_status'],'unavailable')
        self.assertEqual(self.state(),before)

    def test_canonical_generation_all_families_and_balance(self):
        before=self.state()
        for family in 'ABCDEFG':
            reply=self.call('scenario.generate',{'prompt':'测试场景','format':'contract','scenario_type':family,'seed':42,'reference_date':'2026-10-23'})
            self.assertIsNone(reply['error'],reply)
            scenario=reply['data'];self.assertEqual(scenario['scenario_type'],family)
            self.assertNotIn('expected_insights',scenario);self.assertNotIn('evaluation_only_fields',scenario)
            for a in scenario['accounts']:
                net=sum(t['amount'] for t in scenario['transactions'] if t['account_id']==a['account_id'] and t['status']=='booked')
                self.assertEqual(a['initial_balance_minor']+net,a['balance_minor'])
            package=_load_modules()['organizer'].organize(scenario)
            self.assertTrue(package['views']['cards']['available'])
        self.assertEqual(self.state(),before)

    def test_generation_replay_restart_and_invalid_inputs(self):
        args={'prompt':'配偶生日锁定1000元','scenario_type':'F','seed':42,'reference_date':'2026-10-23'}
        first=self.call('scenario.generate',args,'persisted-scenario')
        self.service=AgentService(self.service.db_path,clock=lambda:self.now[0])
        self.assertEqual(first,self.call('scenario.generate',args,'persisted-scenario'))
        for extra in [{'seed':True},{'scenario_type':'Z'},{'reference_date':'2026-02-30'},{'include_evaluation':True},{'format':'bad'}]:
            reply=self.call('scenario.generate',{**args,**extra})
            self.assertIsNotNone(reply['error'],reply)

    def test_new_chat_routes_to_session_analysis(self):
        self.ready();reply=self.call('chat',{'message':'查看现金流、预算建议并整理数据'})
        self.assertIsNone(reply['error'],reply)
        tools=[x['tool'] for x in reply['data']['results']]
        self.assertIn('analysis',tools)
        self.assertEqual(self.state()['available'],3864000)


class ThirdHttpTests(unittest.TestCase):
    def test_get_post_analysis_and_cookie_isolation(self):
        with TemporaryDirectory() as temp:
            service=AgentService(Path(temp)/'http.sqlite3');server=make_server(service,port=0)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            try:
                origin=f'http://127.0.0.1:{server.server_port}';seq=0
                def post(client,path,payload):
                    nonlocal seq
                    seq+=1
                    request=Request(origin+path,json.dumps(payload).encode(),{'Content-Type':'application/json','Idempotency-Key':f'http-{seq}'})
                    return json.loads(client.open(request).read())
                a=build_opener(HTTPCookieProcessor());b=build_opener(HTTPCookieProcessor())
                for client in [a,b]:post(client,'/api/session',{})
                post(a,'/api/rpc',{'method':'authorize','args':[{'read':True,'trade':False,'subscriptions':False}]})
                for path in ['/api/analysis?tool=bills.summary&month=2026-10','/api/analysis?tool=data.organize&days=30','/api/analysis/status']:
                    reply=json.loads(a.open(origin+path).read());self.assertIsNone(reply['error'],reply)
                denied=post(b,'/api/analysis',{'tool':'data.organize'})
                self.assertEqual(denied['error']['code'],'SCOPE_DENIED')
                reply=post(a,'/api/scenarios/generate',{'prompt':'配偶生日1000元','seed':42,'reference_date':'2026-10-23'})
                self.assertEqual(reply['data']['scenario_type'],'F')
                self.assertNotIn('expected_insights',reply['data'])
                forbidden=post(a,'/api/analysis',{'tool':'analysis.pipeline','args':{'include_evaluation':True}})
                self.assertEqual(forbidden['error']['code'],'INVALID_ARGUMENT')
            finally:server.shutdown();server.server_close();worker.join(3)
