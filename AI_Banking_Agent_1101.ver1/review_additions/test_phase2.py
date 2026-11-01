from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
from unittest.mock import patch
import unittest,json
from first_agent.service import BASE,Fault
from review_additions.runtime import ReviewService
from review_additions.live_knowledge import LiveKnowledge
from review_additions.releases import Releases

class PhaseTwoTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.service=ReviewService(self.path/'ledger.sqlite3')
        self.sid=self.service.create_session()

    def test_audit_chain_survives_restart(self):
        self.service.call(self.sid,'knowledge',{'question':'什么是LPR'})
        other=ReviewService(self.path/'ledger.sqlite3')
        with closing(other.connect()) as db:self.assertGreater(other.audit_chain.verify(db)['entries'],0)

    def test_tampering_blocks_mutation_atomically(self):
        with self.service.transaction() as db:
            before=db.execute('SELECT state FROM sessions WHERE sid=?',(self.sid,)).fetchone()[0]
            db.execute("UPDATE audit SET status='forged'")
        with self.assertRaises(Fault):self.service.call(self.sid,'rpc',{'method':'authorize','args':[{'read':True}]})
        with closing(self.service.connect()) as db:self.assertEqual(db.execute('SELECT state FROM sessions WHERE sid=?',(self.sid,)).fetchone()[0],before)

    def test_missing_chain_entry_detected(self):
        with self.service.transaction() as db:db.execute('DELETE FROM review_audit_chain')
        with closing(self.service.connect()) as db,self.assertRaises(Fault):self.service.audit_chain.verify(db)

    def test_unpublished_mode_rejects_even_lexicon_and_no_external_fallback(self):
        store=Releases(self.path/'release.sqlite3');self.service.rag.live_knowledge=LiveKnowledge(store.path)
        with patch.object(self.service.external,'fallback') as fallback:
            r=self.service.call(self.sid,'knowledge',{'question':'什么是LPR'})
            self.assertEqual(r['error']['code'],'REVIEW_REQUIRED');fallback.assert_not_called()

    def test_published_version_used_and_rollback_visible_without_restart(self):
        store=Releases(self.path/'release.sqlite3')
        chunks=json.loads((BASE/'knowledge/index.json').read_text(encoding='utf-8'))['chunks']
        report=self.path/'evaluation.json';report.write_text(json.dumps({'summary':{'citation_integrity_failures':0,'ledger_unchanged':True,'questions':1}}))
        versions=[]
        for chunk in chunks[:2]:
            cid=store.propose('author',[chunk['id']]);store.approve(cid,'reviewer',report,True);versions.append(store.publish(cid,'reviewer'))
        live=LiveKnowledge(store.path);self.service.rag.live_knowledge=live
        first=self.service.call(self.sid,'knowledge',{'question':'什么是LPR'},'same-key')
        self.assertEqual(first['data']['review_version'],versions[1])
        store.rollback(versions[0],'reviewer')
        second=self.service.call(self.sid,'knowledge',{'question':'什么是LPR'},'same-key')
        self.assertEqual(second['data']['review_version'],versions[0])
        self.assertEqual([x['id'] for x in live.snapshot()[1]['chunks']],[chunks[0]['id']])

    def test_changed_source_refuses_published_version(self):
        store=Releases(self.path/'release.sqlite3')
        chunk=json.loads((BASE/'knowledge/index.json').read_text(encoding='utf-8'))['chunks'][0]
        report=self.path/'evaluation.json';report.write_text(json.dumps({'summary':{'citation_integrity_failures':0,'ledger_unchanged':True,'questions':1}}))
        cid=store.propose('author',[chunk['id']]);store.approve(cid,'reviewer',report,True);store.publish(cid,'reviewer')
        live=LiveKnowledge(store.path)
        with patch.object(live.store,'source',return_value={'changed':True}),self.assertRaises(Fault):live.snapshot()

    def test_nested_identity_and_excessive_structure_rejected(self):
        for args in ({'method':'authorize','args':[{'read':True,'user_id':'other'}]},
                     {'method':'authorize','args':[{'read':True,'roles':['admin']}]},
                     {'method':'assistant','args':['x'*100000]}):
            response=self.service.call(self.sid,'rpc',args)
            self.assertIsNotNone(response['error'])

    def test_saved_checkpoint_detects_whole_tail_removal(self):
        from review_additions.check_audit import verify
        self.service.call(self.sid,'knowledge',{'question':'什么是LPR'})
        point=self.path/'checkpoint.json';point.write_text(json.dumps(verify(self.service.db_path)))
        with self.service.transaction() as db:
            seq,aid=db.execute('SELECT seq,audit_id FROM review_audit_chain ORDER BY seq DESC LIMIT 1').fetchone()
            db.execute('DELETE FROM audit WHERE id=?',(aid,));db.execute('DELETE FROM review_audit_chain WHERE seq=?',(seq,))
        with self.assertRaises(Fault):verify(self.service.db_path,point)
