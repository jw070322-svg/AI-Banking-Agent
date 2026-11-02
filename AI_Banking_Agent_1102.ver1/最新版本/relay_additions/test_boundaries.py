import http.client
import json
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import patch
from uuid import uuid4

from first_agent.service import BASE, Fault
from review_additions.releases import Releases
from review_additions.runtime import ReviewRAG
from first_agent.vendor.rag.service import RAGService
from relay_additions.runtime import RelayService, make_server, ScopedLiveKnowledge


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = RelayService(self.root / 'ledger.sqlite3')
        self.sid = self.service.create_session()
        self.store = Releases(self.root / 'review.sqlite3')
        self.live = ScopedLiveKnowledge(self.store.path)
        self.service.rag.live_knowledge = self.live
        self.chunks = json.loads((BASE / 'knowledge/index.json').read_text(encoding='utf-8'))['chunks']
        self.report = self.root / 'eval.json'
        self.report.write_text(json.dumps({'summary': {'citation_integrity_failures': 0, 'ledger_unchanged': True, 'questions': 1}}), encoding='utf-8')

    def publish(self, chunk):
        cid = self.store.propose('author', [chunk['id']])
        self.store.approve(cid, 'reviewer', self.report, True)
        return self.store.publish(cid, 'reviewer')

    def test_unpublished_direct_search_fails_closed(self):
        # The inherited method returns the full corpus here. New entry refuses.
        with self.assertRaises(Fault) as cm:
            self.service.rag.search('为什么余额减少')
        self.assertEqual(cm.exception.code, 'REVIEW_REQUIRED')

    def test_search_and_sparse_fallback_use_only_approved_chunk(self):
        version = self.publish(self.chunks[1])
        self.assertTrue(self.service.rag.search('什么是现金流'))
        for question in ['为什么余额减少', '什么是现金流', 'Explain LPR']:
            for item in self.service.rag.search(question, 10):
                self.assertEqual(item['id'], self.chunks[1]['id'])
                self.assertEqual(item['review_version'], version)

    def test_source_only_approved_lines_and_version_bound(self):
        chunk = self.chunks[0]; version = self.publish(chunk)
        page = self.live.source_page(version, chunk['document_id']).decode()
        self.assertIn('id="L%d"' % chunk['start_line'], page)
        unapproved = next(c for c in self.chunks if c['document_id']==chunk['document_id'] and c['start_line']>chunk['end_line'])
        self.assertNotIn('id="L%d"' % unapproved['start_line'], page)
        self.publish(self.chunks[1])
        with self.assertRaises(Fault) as cm:
            self.live.source_page(version, chunk['document_id'])
        self.assertEqual(cm.exception.status, 409)

    def test_unapproved_document_and_modified_source_rejected(self):
        version = self.publish(self.chunks[0])
        other = next(c for c in self.chunks if c['document_id']!=self.chunks[0]['document_id'])
        with self.assertRaises(Fault): self.live.source_page(version, other['document_id'])
        with patch.object(self.live.store, 'source', return_value={'changed': True}):
            with self.assertRaises(Fault): self.live.search('为什么余额减少')
            with self.assertRaises(Fault): self.live.source_page(version, self.chunks[0]['document_id'])

    def test_ask_citations_bind_to_snapshot(self):
        version = self.publish(self.chunks[1])
        answer = self.service.rag.ask('什么是现金流')
        self.assertEqual(answer['review_version'], version)
        self.assertTrue(answer['citations'])
        self.assertTrue(all(c['citation_uri'].startswith('/relay/source/'+version+'/') for c in answer['citations']))

    def test_plain_mode_preserves_answers(self):
        self.service.rag.live_knowledge = None
        original = ReviewRAG(RAGService(BASE/'knowledge/index.json'))
        for q in ['什么是LPR', '为什么余额减少', '火星独角兽的量子冰淇淋兑换代码']:
            left, right = original.ask(q), self.service.rag.ask(q)
            self.assertEqual((left['status'],left['answer']), (right['status'],right['answer']))

    def test_delete_during_inflight_request_prevents_late_repopulation(self):
        xp=self.service.experience; old=xp.consent(self.sid,{'enabled':True})
        started=Event(); proceed=Event(); results=[]; errors=[]
        def blocked_call(*args, **kwargs):
            started.set()
            if not proceed.wait(5): raise RuntimeError('test timeout')
            return self.service.envelope({'status':'succeeded'})
        def invoke():
            try: results.append(self.service.call(self.sid,'snapshot'))
            except Exception as exc: errors.append(exc)
        with patch('first_agent.service.AgentService.call', side_effect=blocked_call):
            worker=Thread(target=invoke);worker.start()
            try:
                self.assertTrue(started.wait(5))
                xp.delete(self.sid,{'confirmation':'删除操作摘要'})
                fresh=xp.consent(self.sid,{'enabled':True})
            finally:
                proceed.set();worker.join(5)
        self.assertFalse(worker.is_alive());self.assertFalse(errors);self.assertEqual(len(results),1)
        self.assertNotEqual(old['epoch'],fresh['epoch'])
        self.assertEqual(xp.query(self.sid,{})['items'],[])

    def test_real_http_blocks_full_source_and_stale_version(self):
        version=self.publish(self.chunks[0]);doc=self.chunks[0]['document_id']
        server=make_server(self.service,port=0)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,cookie=True):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
            conn.request('GET',path,headers={'Cookie':'banking_review_1029='+self.sid} if cookie else {})
            response=conn.getresponse();body=response.read();status=response.status;conn.close()
            return status,body
        try:
            url='/relay/source/'+version+'/'+doc
            self.assertEqual(request(url,False)[0],401)
            self.assertEqual(request(url)[0],200)
            self.assertEqual(request('/review/source/'+doc)[0],403)
            self.publish(self.chunks[1])
            self.assertEqual(request(url)[0],409)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__ == '__main__': unittest.main()
