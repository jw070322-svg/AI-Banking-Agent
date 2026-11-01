import json, threading, unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from first_agent.external_services import ExternalServices, SearchParser, public_question, request, MODEL
from first_agent.service import AgentService, Fault

def answer(text='久期衡量债券价格对利率变动的敏感程度。',reason='stop'):
    return {'status':'ok','body':json.dumps({'choices':[{'finish_reason':reason,'message':{'content':text}}]})}

class ExternalTests(unittest.TestCase):
    def test_parser_ignores_navigation_and_javascript(self):
        p=SearchParser();p.feed('<a href="https://example.org/">nav</a><h3><a href="javascript:alert(1)">bad</a></h3><h3><a href="https://example.org/a"><em>久期</em>定义</a></h3>')
        self.assertEqual(p.hits,[{'title':'久期定义','url':'https://example.org/a'}])
    def test_private_data_rejected_before_network(self):
        for q in ('我的账户余额','手机号13800138000','API_KEY=abc','银行卡号6222000000000000','我家生日预算','https://localhost/a'):
            with self.subTest(q=q),self.assertRaises(ValueError): public_question(q)
    def test_fixed_endpoint_blocks_ssrf(self):
        for u in ('http://169.254.169.254/latest','https://www.baidu.com.evil.test/s','http://127.0.0.1:8794/admin','https://user:secret@www.baidu.com/s'):
            with self.assertRaises(ValueError):request(u)
    def test_captcha_not_reported_as_results(self):
        e=ExternalServices(lambda *a,**k:{'status':'needs_verification','http_status':403})
        r=e.baidu('什么是久期');self.assertEqual(r['status'],'needs_verification');self.assertEqual(r['items'],[])
    def test_result_caching_and_real_parser(self):
        calls=[]
        def transport(*a,**k):calls.append(a);return {'status':'ok','body':'<h3><a href="https://example.org/a">久期定义</a></h3>'}
        e=ExternalServices(transport);self.assertEqual(len(e.baidu('久期定义')['items']),1);self.assertTrue(e.baidu('久期定义')['cached']);self.assertEqual(len(calls),1)
    def test_no_results_is_not_connected_search(self):
        e=ExternalServices(lambda *a,**k:{'status':'ok','body':'<title>首页</title>'})
        self.assertEqual(e.baidu('债券久期')['status'],'no_results')
    def test_free_llama_fallback_with_no_tools_or_bank_state(self):
        calls=[]
        def transport(url,payload=None,**kw):
            calls.append((url,payload));return answer() if payload else {'status':'needs_verification'}
        r=ExternalServices(transport).fallback('什么是久期',{'status':'no_evidence'})
        self.assertEqual(r['status'],'needs_evidence');self.assertTrue(r['model_response_received']);self.assertEqual(r['api_fee'],0);self.assertEqual(r['citations'],[])
        payload=calls[0][1];self.assertEqual(payload['model'],MODEL);self.assertNotIn('tools',payload);self.assertEqual(len(payload['messages']),2)
        self.assertEqual(calls[0][0],'http://127.0.0.1:8811/v1/chat/completions');self.assertFalse(r['external_data_sent'])
    def test_current_facts_do_not_use_model_memory(self):
        calls=[]
        def transport(*a,**k):calls.append(a);return {'status':'needs_verification'}
        r=ExternalServices(transport).fallback('今天定期利率是多少',{'status':'no_evidence'})
        self.assertEqual(r['status'],'needs_evidence');self.assertEqual(len(calls),0)
    def test_privacy_denial_never_calls_any_provider(self):
        def denied(*a,**k):raise AssertionError('must not send')
        r=ExternalServices(denied).fallback('我的工资12345元',{'status':'no_evidence'})
        self.assertEqual(r['fallback_status'],'privacy_blocked');self.assertFalse(r['external_data_sent'])
    def test_truncated_reasoning_and_tool_outputs_rejected(self):
        for response in (answer('unfinished','length'),answer('<think>secret</think>answer'),{'status':'ok','body':'{"choices":[]}'}, {'status':'ok','body':'bad json'}):
            with self.subTest(response=response):
                r=ExternalServices(lambda *a,**k:response).generate('什么是久期');self.assertEqual(r['status'],'unavailable')
    def test_model_status_checks_alias(self):
        e=ExternalServices(lambda *a,**k:{'status':'ok','body':json.dumps({'data':[{'id':MODEL}]})})
        self.assertEqual(e.model_status()['status'],'ready');self.assertFalse(e.status()['paid_api_enabled'])
    def test_local_life_links_are_official_and_not_merchant_data(self):
        e=ExternalServices();r=e.links('上海','蛋糕');self.assertEqual(len(r['items']),2)
        self.assertEqual(r['status'],'external_search_link');self.assertFalse(e.status()['meituan']['merchant_api_connected'])
        self.assertEqual(r['items'][0]['url'],'https://www.meituan.com/')
        with self.assertRaises(ValueError):e.links('<script>','蛋糕')

class ServiceExternalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.s=AgentService(Path(self.tmp.name)/'state.sqlite3');self.sid=self.s.create_session();self.calls=[]
        def transport(url,payload=None,**kw):
            self.calls.append((url,payload));return answer() if payload else {'status':'needs_verification'}
        self.s.external=ExternalServices(transport)
    def tearDown(self):self.tmp.cleanup()
    def test_known_concept_remains_local(self):
        r=self.s.call(self.sid,'knowledge',{'question':'什么是夏普率'},'known')
        self.assertEqual(r['data']['status'],'grounded');self.assertEqual(self.calls,[])
    def test_idempotency_and_ledger_unchanged(self):
        with closing(self.s.connect()) as db:before=db.execute('SELECT state FROM sessions').fetchone()[0]
        with patch.object(self.s.rag,'ask',return_value={'status':'no_evidence'}):
            a=self.s.call(self.sid,'knowledge',{'question':'什么是辛普森悖论'},'same');b=self.s.call(self.sid,'knowledge',{'question':'什么是辛普森悖论'},'same')
        self.assertEqual(a,b);self.assertEqual(len(self.calls),1)
        with closing(self.s.connect()) as db:after=db.execute('SELECT state FROM sessions').fetchone()[0]
        self.assertEqual(before,after)
        with self.assertRaises(Fault):self.s.call(self.sid,'knowledge',{'question':'另一个问题'},'same')
    def test_network_call_does_not_lock_ledger(self):
        def transport(*a,**k):
            with self.s.transaction() as db: db.execute('SELECT 1')
            return {'status':'needs_verification'}
        self.s.external=ExternalServices(transport)
        self.s.call(self.sid,'external.search',{'question':'什么是久期','public_search_approved':True},'lock')
    def test_session_and_query_validation(self):
        with self.assertRaises(Fault):self.s.call('unknown','external.status')
        r=self.s.call(self.sid,'external.search',{'question':'我的账户余额','public_search_approved':True},'private')
        self.assertEqual(r['status'],'rejected');self.assertEqual(self.calls,[])
    def test_chat_uses_same_fallback(self):
        with patch.object(self.s.rag,'ask',return_value={'status':'no_evidence'}):
            r=self.s.call(self.sid,'chat',{'message':'什么是辛普森悖论'},'chat')
        self.assertEqual(r['data']['results'][0]['result']['status'],'needs_evidence')
    def test_audit_export_exact_eight_fields(self):
        blocked=self.s.call(self.sid,'external.search',{'question':'久期的定义'},'no-approval')
        self.assertEqual(blocked['error']['code'],'SEARCH_APPROVAL_REQUIRED');self.assertEqual(self.calls,[])
        self.s.call(self.sid,'external.search',{'question':'久期的定义','public_search_approved':True},'audit')
        data=self.s.call(self.sid,'audit.export')['data']
        record=next(x for x in data['records'] if x['tool']=='external.search')
        self.assertEqual(set(record),{'user_id','intent','tool','input','output','risk_check','approval','timestamp'})
        self.assertEqual(record['approval'],'not_granted')
        self.assertNotIn('久期的定义',json.dumps(data,ensure_ascii=False))
        with closing(self.s.connect()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM research_requests').fetchone()[0],0)

if __name__=='__main__':unittest.main()
