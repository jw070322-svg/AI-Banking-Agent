"""Conversational slot filling hands off to the existing form without creating a payment."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from first_agent.service import AgentService

class UnifiedAssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.service=AgentService(Path(self.temp.name)/'fill.sqlite3');self.sid=self.service.create_session();self.n=0
    def rpc(self,method,*args):
        self.n+=1;return self.service.call(self.sid,'rpc',{'method':method,'args':list(args)},str(self.n))
    def say(self,text):return self.rpc('assistant',text)
    def state(self):return self.service.call(self.sid,'snapshot')['data']['state']
    def ready(self):self.rpc('authorize',{'read':True,'trade':True,'subscriptions':True,'cards':True})
    def assert_filled(self,r,name='小王',amount=80000):
        self.assertIsNone(r['error'],r);d=r['data'];self.assertEqual(d['route'],'transfer-form');self.assertEqual(d['transfer']['recipient_alias'],name);self.assertEqual(d['transfer']['amount_minor'],amount)
        self.assertEqual(self.state()['available'],3864000);self.assertEqual(self.state()['transfer_ops'],[])
    def test_followup_amount_units_and_bare_amount(self):
        for amount in ['800元','800块','800']:
            self.say('取消');r=self.say('给小王转账');self.assertEqual(r['data']['route'],'transfer-conversation');self.assert_filled(self.say(amount));self.assertEqual(self.state()['operations'],[])
    def test_context_persists_restart_and_refresh(self):
        self.say('给林晓转账');self.state();self.service=AgentService(self.service.db_path);self.assert_filled(self.say('300元'),'林晓',30000)
    def test_no_context_never_uses_previous_recipient(self):
        self.say('给小王转账');self.say('取消');r=self.say('800元');self.assertNotEqual(r['data'].get('route'),'transfer-form');self.assertEqual(self.state()['operations'],[])
    def test_other_task_clears_slots_and_preserves_routes(self):
        self.say('给小王转账');self.assertEqual(self.say('查看账户余额')['data']['route'],'overview');self.assertIsNone(self.state()['assistant_transfer'])
        self.assertNotEqual(self.say('800元')['data'].get('route'),'transfer-form')
        self.assertEqual(self.say('推荐低风险理财产品')['data']['route'],'wealth')
    def test_correction_invalidates_form_confirmation_even_when_invalid(self):
        self.ready();self.assert_filled(self.say('给小王转账800元'));o=self.rpc('propose','transfer','R-WANG',80000,{'cardId':'CARD-DEBIT'})['data']
        self.say('改成-50元');self.assertIsNotNone(self.rpc('execute',o['id'],'success')['error']);self.assertEqual(self.state()['available'],3864000)
    def test_final_form_is_only_execution_path_and_idempotent(self):
        self.assert_filled(self.say('给林晓转账300元'),'林晓',30000)
        self.assertIsNotNone(self.rpc('propose','transfer','R-LIN',30000,{'cardId':'CARD-DEBIT'})['error'])
        self.ready();o=self.rpc('propose','transfer','R-LIN',30000,{'cardId':'CARD-DEBIT'})['data'];self.assertEqual(self.state()['available'],3864000)
        self.assertIsNone(self.rpc('execute',o['id'],'success')['error']);self.assertIsNotNone(self.rpc('execute',o['id'],'success')['error']);self.assertEqual(self.state()['available'],3834000)
        self.assertEqual(self.say('改成900元')['data']['reason_code'],'CANCEL_NOT_AVAILABLE')
    def test_invalid_and_unknown_inputs_do_not_create_operations(self):
        for text in ['给小李转账300元','给小王转账-800元','给小王转账1e3元','明天给小王转账800元','给小王转账800元再给林晓转200元']:
            self.assertNotEqual(self.say(text)['data']['route'],'transfer-form')
        self.assertEqual(self.state()['operations'],[]);self.assertEqual(self.state()['available'],3864000)
    def test_correction_and_cancel_are_session_bound(self):
        self.say('给小王转账');self.assert_filled(self.say('800元'));self.assert_filled(self.say('改成900元'),amount=90000)
        other=self.service.create_session();r=self.service.call(other,'rpc',{'method':'assistant','args':['改成900元']},'other');self.assertEqual(r['data']['reason_code'],'CONTEXT_REQUIRED')
        self.ready();o=self.rpc('propose','transfer','R-WANG',90000,{'cardId':'CARD-DEBIT'})['data'];self.say('取消');self.assertIsNotNone(self.rpc('execute',o['id'],'success')['error'])
    def test_amount_without_context_asks_recipient_then_completes(self):
        r=self.say('800元');self.assertEqual(r['data']['reason_code'],'MISSING_SLOT');self.assertIsNone(self.state()['assistant_transfer']['recipient_alias'])
        self.assert_filled(self.say('小王'));self.assertEqual(self.state()['operations'],[])
    def test_manual_form_changes_bind_the_actual_recipient_and_amount(self):
        self.assert_filled(self.say('给小王转账800元'));self.ready()
        o=self.rpc('propose','transfer','R-LIN',30000,{'cardId':'CARD-DEBIT'})['data']
        r=self.say('改成500元');self.assert_filled(r,'林晓',50000)
        self.assertIsNotNone(self.rpc('execute',o['id'],'success')['error'])
