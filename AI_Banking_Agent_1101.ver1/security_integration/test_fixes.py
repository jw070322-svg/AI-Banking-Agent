"""G01 replay authorization and D01 portable publication acceptance."""
import hashlib,json,unittest,io
from contextlib import redirect_stdout
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
from urllib.request import build_opener,HTTPCookieProcessor
from security_integration.runtime import IntegratedService,make_server
from security_integration.publication import verify_publication,verify_project
from review_additions.test_review import original_http

class ReplayTests(unittest.TestCase):
    call=original_http.LatestFrontendHTTPTests.call
    rpc=original_http.LatestFrontendHTTPTests.rpc
    ready=original_http.LatestFrontendHTTPTests.ready
    state=original_http.LatestFrontendHTTPTests.state
    tearDown=original_http.LatestFrontendHTTPTests.tearDown
    def setUp(self):
        self.temp=TemporaryDirectory();self.service=IntegratedService(Path(self.temp.name)/'s.sqlite3')
        self.server=make_server(self.service,port=0);self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port);self.client=build_opener(HTTPCookieProcessor());self.call('/api/session',{})
    def revoke(self):
        self.assertIsNone(self.rpc('authorize',{'read':False,'trade':False,'subscriptions':False,'cards':False})['error'])
    def test_G01_old_and_new_key_denied_after_revocation(self):
        self.ready();first=self.rpc('summary','2026-10',key='K');self.assertIsNone(first['error'])
        self.revoke()
        for key in ('K','new-key'):
            response=self.rpc('summary','2026-10',key=key)
            self.assertEqual(response['error']['code'],'SCOPE_DENIED');self.assertIsNone(response['data'])
    def test_chat_preview_cache_requires_current_trade_scope(self):
        self.ready();args={'message':'给小王转账800元'}
        first=self.call('/api/chat',args,key='chat-draft')
        self.assertIsNone(first['error']);self.assertEqual(first,self.call('/api/chat',args,key='chat-draft'))
        self.revoke();r=self.call('/api/chat',args,key='chat-draft')
        self.assertEqual(r['error']['code'],'SCOPE_DENIED');self.assertIsNone(r['data'])
    def test_expired_authorization_blocks_both_keys(self):
        self.ready();self.assertIsNone(self.rpc('summary','2026-10',key='K')['error'])
        clock=self.service.clock
        with patch.object(self.service,'clock',side_effect=lambda:clock()+86401):
            for key in ('K','fresh'):
                r=self.rpc('summary','2026-10',key=key);self.assertEqual(r['error']['code'],'SCOPE_EXPIRED');self.assertIsNone(r['data'])
    def test_authorized_execution_replay_returns_receipt_once_and_after_restart(self):
        self.ready();op=self.rpc('propose','transfer','R-LIN',30000,{'cardId':'CARD-DEBIT'})['data']
        first=self.rpc('execute',op['id'],'success',key='paid')
        self.assertIsNone(first['error']);self.assertEqual(first,self.rpc('execute',op['id'],'success',key='paid'))
        with closing(self.service.connect()) as db:
            sid=db.execute('SELECT sid FROM sessions LIMIT 1').fetchone()[0]
            self.assertEqual(db.execute("SELECT count(*) FROM guardian_dispatch WHERE action='rpc.execute'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM guardian_dispatch WHERE action='rpc.execute.cache_read'").fetchone()[0],1)
        restarted=IntegratedService(self.service.db_path)
        result=restarted.call(sid,'rpc',{'method':'execute','args':[op['id'],'success']},'paid')
        self.assertEqual(first,result);self.assertEqual(self.state()['available'],3834000)
    def test_other_session_cannot_read_cached_summary(self):
        self.ready();first=self.rpc('summary','2026-10',key='K');self.assertIsNone(first['error'])
        other=build_opener(HTTPCookieProcessor());self.call('/api/session',{},client=other)
        r=self.call('/api/rpc',{'method':'summary','args':['2026-10']},client=other,key='K')
        self.assertEqual(r['error']['code'],'SCOPE_DENIED');self.assertIsNone(r['data'])
    def test_removed_resource_receipt_is_not_returned(self):
        self.ready();op=self.rpc('propose','transfer','R-LIN',30000,{'cardId':'CARD-DEBIT'})['data']
        self.assertIsNone(self.rpc('execute',op['id'],'success',key='paid')['error'])
        with self.service.transaction() as db:
            sid=db.execute('SELECT sid FROM sessions LIMIT 1').fetchone()[0];state=self.service.load(db,sid)
            state['operations']=[x for x in state['operations'] if x['id']!=op['id']]
            db.execute('UPDATE sessions SET state=? WHERE sid=?',(json.dumps(state),sid))
        r=self.rpc('execute',op['id'],'success',key='paid');self.assertEqual(r['error']['code'],'NOT_FOUND');self.assertIsNone(r['data'])
    def test_regrant_allows_read_only_cached_result(self):
        self.ready();first=self.rpc('summary','2026-10',key='K');self.revoke()
        self.assertIsNotNone(self.rpc('summary','2026-10',key='K')['error'])
        self.ready();self.assertEqual(first,self.rpc('summary','2026-10',key='K'))
    def test_expired_verification_cache_does_not_return_old_capability(self):
        self.ready();op=self.call('/api/transfers/preview',{'amount_minor':150000,'beneficiary_name':'林晓'})['data']
        args={'operation_id':op['id'],'code':'246810'}
        self.assertIsNone(self.call('/api/transfers/verify',args,key='proof')['error'])
        clock=self.service.clock
        with patch.object(self.service,'clock',side_effect=lambda:clock()+121):
            r=self.call('/api/transfers/verify',args,key='proof');self.assertEqual(r['error']['code'],'AUTH_EXPIRED');self.assertIsNone(r['data'])

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'first_agent').mkdir();(self.root/'first_agent/service.py').write_text('source')
        archive=self.root/'history_version/launchers_before_1101';archive.mkdir(parents=True)
        (archive/'old.bat').write_text('launcher')
        sha=lambda s:hashlib.sha256(s.encode()).hexdigest()
        self.baseline={'first_agent/service.py':sha('source'),'old.bat':sha('launcher'),'modules/example/runtime/idempotency.sqlite3':sha('runtime')}
        self.manifest={'mappings':{k:'RenamedArchive/最新版本/'+('history_version/launchers_before_1101/old.bat' if k=='old.bat' else k) for k in self.baseline},'omitted_runtime_and_cache':['modules/example/runtime/idempotency.sqlite3']}
    def test_D01_archived_paths_and_explicit_runtime_exclusion(self):
        result=verify_publication(self.root,self.baseline,self.manifest);self.assertEqual(result['checked'],2);self.assertEqual(len(result['excluded_runtime']),1)
    def test_tampered_source_rejected(self):
        (self.root/'first_agent/service.py').write_text('tampered')
        with self.assertRaises(ValueError):verify_publication(self.root,self.baseline,self.manifest)
    def test_missing_archive_rejected(self):
        (self.root/'history_version/launchers_before_1101/old.bat').unlink()
        with self.assertRaises(ValueError):verify_publication(self.root,self.baseline,self.manifest)
    def test_source_cannot_be_disguised_as_omitted_runtime(self):
        (self.root/'first_agent/service.py').unlink();self.manifest['omitted_runtime_and_cache'].append('first_agent/service.py')
        with self.assertRaises(ValueError):verify_publication(self.root,self.baseline,self.manifest)
    def test_traversal_and_source_relocation_rejected(self):
        for path in ('RenamedArchive/最新版本/../service.py','RenamedArchive/最新版本/history_version/service.py'):
            self.manifest['mappings']['first_agent/service.py']=path
            with self.assertRaises(ValueError):verify_publication(self.root,self.baseline,self.manifest)
    def test_registered_exact_change_and_subsequent_tamper(self):
        f=self.root/'first_agent/service.py';f.write_text('fixed')
        changes={'first_agent/service.py':{'before':self.baseline['first_agent/service.py'],'after':hashlib.sha256(b'fixed').hexdigest(),'reason':'G01'}}
        self.assertEqual(len(verify_publication(self.root,self.baseline,self.manifest,changes)['authorized_changes']),1)
        f.write_text('changed again')
        with self.assertRaises(ValueError):verify_publication(self.root,self.baseline,self.manifest,changes)
    def test_actual_delivered_project_can_verify(self):
        root=Path(__file__).resolve().parents[1];result=verify_project(root)
        self.assertEqual(result['unexpected_changes'],[]);self.assertGreaterEqual(result['checked'],900)

class GenerationTests(unittest.TestCase):
    def test_failed_tests_do_not_call_report_generator(self):
        from security_integration import self_assess
        from types import SimpleNamespace
        with redirect_stdout(io.StringIO()), TemporaryDirectory() as tmp, patch.object(self_assess,'ROOT',Path(tmp)), patch.object(self_assess.subprocess,'run',return_value=SimpleNamespace(returncode=1)) as run:
            self.assertEqual(self_assess.main(),1)
            self.assertEqual(run.call_count,1)
            status=json.loads((Path(tmp)/'reports/g01-d01-fix/generation-status.json').read_text())
            self.assertEqual(status['status'],'failed')
            self.assertEqual(status['failed_step'],'security_integration.verify')
    def test_generation_stops_on_publication_error(self):
        from security_integration import self_assess
        from types import SimpleNamespace
        with redirect_stdout(io.StringIO()), TemporaryDirectory() as tmp, patch.object(self_assess,'ROOT',Path(tmp)), patch.object(self_assess.subprocess,'run',side_effect=[SimpleNamespace(returncode=0),SimpleNamespace(returncode=1)]) as run:
            self.assertEqual(self_assess.main(),1);self.assertEqual(run.call_count,2)
            self.assertEqual(json.loads((Path(tmp)/'reports/g01-d01-fix/generation-status.json').read_text())['status'],'failed')
