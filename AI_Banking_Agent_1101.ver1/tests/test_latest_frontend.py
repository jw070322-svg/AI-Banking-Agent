from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request,build_opener,HTTPCookieProcessor
from urllib.error import HTTPError
import json,threading,unittest,uuid
from first_agent.service import AgentService
from first_agent.server import make_server

class LatestFrontendHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.service=AgentService(Path(self.temp.name)/'latest.sqlite3');self.server=make_server(self.service,port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.base='http://127.0.0.1:'+str(self.server.server_port);self.client=build_opener(HTTPCookieProcessor());self.call('/api/session',{})
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def call(self,path,body=None,token=None,client=None,key=None):
        headers={};data=None
        if body is not None:headers={'Content-Type':'application/json','Idempotency-Key':key or uuid.uuid4().hex};data=json.dumps(body).encode()
        if token:headers['X-Developer-Token']=token
        try:r=(client or self.client).open(Request(self.base+path,data=data,headers=headers))
        except HTTPError as e:r=e
        return json.loads(r.read())
    def rpc(self,method,*args,token=None,key=None):return self.call('/api/rpc',{'method':method,'args':list(args)},token,key=key)
    def ready(self):self.assertIsNone(self.rpc('authorize',{'read':True,'trade':True,'subscriptions':True,'cards':True})['error'])
    def state(self):return self.call('/api/snapshot')['data']['state']
    def login(self):return self.call('/api/developer/login',{'code':'bnbu'})['data']['token']
    def transfer(self,mode='success',token=None):
        o=self.rpc('propose','transfer','R-LIN',30000,{'cardId':'CARD-DEBIT'})['data'];self.assertIsNone(self.rpc('execute',o['id'],mode,token=token)['error']);return o
    def test_live_entry_uses_latest_async_client_and_styles(self):
        html=self.client.open(self.base+'/').read().decode();self.assertIn('backend-client.js',html);self.assertIn('customer-language.js',html);self.assertNotIn('agent-panel.js',html);self.assertNotIn('server-bridge.js',html);self.assertNotIn('local-store.js',html)
        script=self.client.open(self.base+'/backend-client.js').read().decode();self.assertNotIn('XMLHttpRequest',script.replace('no synchronous XHR',''));self.assertNotIn('localStorage.',script)
    def test_enhanced_assistant_templates_and_backend_tools(self):
        r=self.rpc('interpret','给林晓转300块')['data'];self.assertEqual(r['transfer']['recipientId'],'R-LIN');self.assertEqual(r['transfer']['amountMinor'],30000)
        self.assertEqual(self.rpc('interpret','分析现金流与预算')['data']['route'],'finance');self.assertEqual(self.rpc('interpret','什么是债务比率')['data']['route'],'knowledge');self.assertEqual(self.state()['operations'],[])
    def test_rpc_transfer_changes_one_sqlite_ledger_and_reloads(self):
        self.ready();o=self.transfer();s=self.state();self.assertEqual(s['available'],3834000);self.assertEqual(s['externalOut'],30000);self.assertEqual(len(s['transactions']),19)
        self.call('/api/session',{});self.assertEqual(self.state()['available'],3834000);self.assertIsNotNone(self.rpc('execute',o['id'],'success')['error'])
    def test_developer_password_and_unauthorized_controls(self):
        self.assertEqual(self.call('/api/developer/login',{'code':'wrong'})['error']['code'],'DEVELOPER_DENIED')
        self.assertEqual(self.call('/api/developer/reset',{'confirmation':'重置演示'})['error']['code'],'DEVELOPER_REQUIRED')
        self.assertEqual(self.rpc('advance',1)['error']['code'],'DEVELOPER_REQUIRED')
    def test_backend_card_loss_reset_and_restore(self):
        self.ready();o=self.rpc('propose','card_loss','CARD-DEBIT')['data'];self.rpc('verify',o['id'],'246810');self.assertIsNone(self.rpc('execute',o['id'],'success')['error']);self.assertEqual(self.state()['cards'][0]['status'],'lost')
        token=self.login();r=self.call('/api/developer/reset',{'confirmation':'重置演示'},token);self.assertIsNone(r['error']);s=self.state();self.assertEqual(s['cards'][0]['status'],'active');self.assertEqual(s['available'],3864000);self.assertEqual(s['operations'],[]);self.assertFalse(s['consent']['trade'])
        self.assertIsNone(self.call('/api/developer/restore',{'confirmation':'恢复备份'},token)['error']);self.assertEqual(self.state()['cards'][0]['status'],'lost')
    def test_developer_token_bound_to_session_and_logout(self):
        token=self.login();other=build_opener(HTTPCookieProcessor());self.call('/api/session',{},client=other)
        self.assertEqual(self.call('/api/developer/reset',{'confirmation':'重置演示'},token,other)['error']['code'],'DEVELOPER_REQUIRED')
        self.call('/api/developer/logout',{},token);self.assertEqual(self.call('/api/developer/reset',{'confirmation':'重置演示'},token)['error']['code'],'DEVELOPER_REQUIRED')
    def test_unknown_is_readonly_for_customer_and_resolves_once_in_test_mode(self):
        self.ready();token=self.login();o=self.transfer('unknown',token);self.assertEqual(self.state()['available'],3864000)
        self.assertEqual(self.rpc('reconcile',o['id'],'success')['error']['code'],'DEVELOPER_REQUIRED');self.assertIsNone(self.rpc('reconcile',o['id'],'pending')['error']);self.assertEqual(self.state()['available'],3864000)
        self.assertIsNone(self.rpc('reconcile',o['id'],'success',token=token)['error']);self.assertEqual(self.state()['available'],3834000);self.assertIsNotNone(self.rpc('reconcile',o['id'],'success',token=token)['error'])
    def test_subscription_purchase_and_redemption_share_balance(self):
        self.ready();self.rpc('reviewSubscription','video');o=self.rpc('propose','subscription','video')['data'];self.rpc('execute',o['id'],'success');self.assertEqual(self.state()['available'],3864000)
        p=self.rpc('propose','purchase')['data'];self.rpc('verify',p['id'],'246810');self.assertIsNone(self.rpc('execute',p['id'],'success')['error']);self.assertEqual(self.state()['available'],3500000)
        r=self.rpc('propose','redeem','POS-SEED',100000)['data'];self.rpc('verify',r['id'],'246810');self.rpc('execute',r['id'],'success');self.assertEqual(self.state()['available'],3500000)
        token=self.login();self.rpc('advance',1,token=token);self.assertIsNone(self.rpc('settle',r['id'],'success')['error']);s=self.state();self.assertEqual(s['available'],3600000);self.assertEqual(s['available']+sum(p['amount'] for p in s['positions'])+s['externalOut'],s['initialTotal']+s.get('externalIn',0))
