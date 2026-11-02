# 1030 完整新增代码

原文件保持不变。使用新入口进行组合。

## relay_additions/__init__.py

【补全内容（relay_additions/__init__.py）起】

~~~py
"""Additive 1030 verification and approved-source boundary hardening."""

~~~

【补全内容（relay_additions/__init__.py）止】

## relay_additions/runtime.py

【补全内容（relay_additions/runtime.py）起】

~~~py
"""Preserve the inherited ledger and restrict every reviewed retrieval surface."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
import html
import re

from first_agent.service import Fault
from first_agent.vendor.rag.corpus import write_json
from first_agent.vendor.rag.service import RAGService
from review_additions import runtime as inherited
from review_additions.live_knowledge import LiveKnowledge


class ScopedLiveKnowledge(LiveKnowledge):
    def search(self, question, top_k=4, **kwargs):
        version, index = self.snapshot()
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'index.json'
            write_json(path, index)
            evidence = inherited.ReviewRAG(RAGService(path)).search(question, top_k, **kwargs)
        for item in evidence:
            self.bind_citation(item, version)
        return evidence

    @staticmethod
    def bind_citation(item, version):
        item.setdefault('original_citation_uri', item.get('citation_uri'))
        item['citation_uri'] = '/relay/source/' + version + '/' + item['document_id'] + '#L' + str(item['start_line'])
        item['review_version'] = version

    def ask(self, question, top_k=4, **kwargs):
        result = super().ask(question, top_k, **kwargs)
        for item in result.get('evidence', []) + result.get('citations', []):
            self.bind_citation(item, result['review_version'])
        return result

    def source_page(self, version, document_id):
        current, index = self.snapshot()
        if current != version:
            raise Fault('REVIEW_VERSION_CHANGED', '审核版本已切换，请重新提问获取当前引用', 409)
        doc = next((d for d in index['documents'] if d['id'] == document_id), None)
        if doc is None:
            raise Fault('REVIEW_SOURCE_DENIED', '该资料不在当前审核范围中', 403)
        # Keep original line numbers, but never expose unapproved neighboring text.
        lines = {}
        for chunk in index['chunks']:
            if chunk['document_id'] == document_id:
                for number, text in enumerate(chunk['text'].splitlines(), chunk['start_line']):
                    lines[number] = text
        body = ''.join('<div id="L%d"><small>%d</small> %s</div>' % (n, n, html.escape(text))
                       for n, text in sorted(lines.items()))
        return ('<!doctype html><meta charset="utf-8"><title>已审核参考片段</title>'
                '<style>body{max-width:900px;margin:40px auto;padding:20px;font:16px/1.8 system-ui}'
                'pre{white-space:pre-wrap}div:target{background:#e3edff}</style><h1>'
                + html.escape(doc['title']) + '</h1><p>仅展示当前版本已审核片段。项目演示资料，不代表实时银行条款。</p><p>版本：'
                + html.escape(version) + '</p><pre>' + body + '</pre>').encode('utf-8')


class ScopedReviewRAG(inherited.ReviewRAG):
    def search(self, question, top_k=4, **kwargs):
        if self.live_knowledge is not None:
            return self.live_knowledge.search(question, top_k, **kwargs)
        return super().search(question, top_k, **kwargs)


class RelayService(inherited.ReviewService):
    def __init__(self, *args, review_db=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Retain the original corpus/client and the original transaction engine.
        self.rag = ScopedReviewRAG(self.rag.primary.primary)
        if review_db is not None:
            self.rag.live_knowledge = ScopedLiveKnowledge(review_db)


def make_server(service, host='127.0.0.1', port=8803):
    server = inherited.make_server(service, host, port)
    Parent = server.RequestHandlerClass

    class Handler(Parent):
        def do_GET(self):
            path = urlsplit(self.path).path
            live = service.rag.live_knowledge
            guarded = path in {'/review/source-links.js', '/review/experience.css'} or path.startswith('/relay/source/') or (live is not None and path.startswith('/review/source/'))
            if not guarded:
                return super().do_GET()
            try:
                self.safe_host()
                if path == '/review/source-links.js':
                    return self.send_bytes((Path(__file__).parent / 'source-links.js').read_bytes(), 'text/javascript; charset=utf-8')
                if path == '/review/experience.css':
                    css = (inherited.ROOT / 'experience.css').read_bytes() + b'\n' + (Path(__file__).parent / 'experience-layout.css').read_bytes()
                    return self.send_bytes(css, 'text/css; charset=utf-8')
                with closing(service.connect()) as db:
                    service.load(db, self.sid())
                if live is None or path.startswith('/review/source/'):
                    raise Fault('REVIEW_SOURCE_DENIED', '请使用回答中的当前审核版本引用链接', 403)
                match = re.fullmatch(r'/relay/source/([A-Za-z0-9_-]{1,100})/([A-Za-z0-9_-]{1,100})', path)
                if not match:
                    raise Fault('NOT_FOUND', '资料不存在', 404)
                return self.send_bytes(live.source_page(*match.groups()), 'text/html; charset=utf-8')
            except Fault as exc:
                self.send_json(service.envelope(status='rejected', error={'code': exc.code, 'message': exc.message}), exc.status)
            except (OSError, ValueError, KeyError, TypeError):
                self.send_json(service.envelope(status='rejected', error={'code': 'REVIEW_UNAVAILABLE',
                    'message': '审核资料暂不可用，请联系维护人员核验'}), 503)

    server.RequestHandlerClass = Handler
    return server

~~~

【补全内容（relay_additions/runtime.py）止】

## relay_additions/test_boundaries.py

【补全内容（relay_additions/test_boundaries.py）起】

~~~py
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

~~~

【补全内容（relay_additions/test_boundaries.py）止】

## relay_additions/verify.py

【补全内容（relay_additions/verify.py）起】

~~~py
"""Offline reports in a NEW folder; never overwrite inherited test evidence."""
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from start import prepare_node
from review_additions import evaluate

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/relay-1030'


def main():
    REPORT.mkdir(parents=True,exist_ok=True)
    node=prepare_node();summaries={}
    for name,suite in [
        ('teammate',unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in ['review_additions.test_review','review_additions.test_phase2'])),
        ('relay',unittest.defaultTestLoader.loadTestsFromName('relay_additions.test_boundaries')),
        ('inherited',unittest.defaultTestLoader.discover(str(ROOT/'tests')))]:
        stream=io.StringIO()
        with patch('first_agent.external_services.request',return_value={'status':'unavailable','reason':'offline_verification'}),patch.object(evaluate,'REPORT',REPORT):
            result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
        (REPORT/(name+'-tests.txt')).write_text(stream.getvalue(),encoding='utf-8')
        summaries[name]={'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()}
        print(name,json.dumps(summaries[name]),flush=True)
    frontend=[]
    for script in [*sorted((ROOT/'tests_frontend').glob('*.cjs')),ROOT/'review_additions/test_frontend.cjs',ROOT/'relay_additions/test_frontend.cjs']:
        run=subprocess.run([node,str(script)],capture_output=True,text=True,encoding='utf-8')
        frontend.append({'script':str(script.relative_to(ROOT)),'code':run.returncode,'stdout':run.stdout,'stderr':run.stderr})
    (REPORT/'frontend.json').write_text(json.dumps(frontend,ensure_ascii=False,indent=2),encoding='utf-8')
    summaries['frontend']={'scripts':len(frontend),'passed':all(r['code']==0 for r in frontend)}
    (REPORT/'tests.json').write_text(json.dumps(summaries,indent=2),encoding='utf-8')
    print('frontend',summaries['frontend'],flush=True)
    return 0 if all(v['passed'] for v in summaries.values()) else 1


if __name__=='__main__': raise SystemExit(main())

~~~

【补全内容（relay_additions/verify.py）止】

## relay_additions/verify_final.py

【补全内容（relay_additions/verify_final.py）起】

~~~py
"""Recheck changed composition only; retain earlier full regression evidence."""
import io
import json
import unittest
from unittest.mock import patch
from relay_additions.verify import ROOT, REPORT
from relay_additions.runtime import RelayService, make_server
from review_additions import test_review, test_phase2, evaluate


def main():
    summary={}
    for name,suite in [('relay-final',unittest.defaultTestLoader.loadTestsFromName('relay_additions.test_boundaries')),
        ('assembled-final',unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in (test_review,test_phase2)))]:
        stream=io.StringIO()
        with patch.object(test_review,'ReviewService',RelayService),patch.object(test_review,'make_server',make_server), \
             patch.object(test_phase2,'ReviewService',RelayService),patch.object(evaluate,'REPORT',REPORT), \
             patch('first_agent.external_services.request',return_value={'status':'unavailable','reason':'offline_verification'}):
            result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
        (REPORT/(name+'.txt')).write_text(stream.getvalue(),encoding='utf-8')
        summary[name]={'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()}
        print(name,summary[name],flush=True)
    with patch.object(evaluate,'REPORT',REPORT),patch.object(evaluate,'ReviewService',RelayService):
        evaluate.run()
    (REPORT/'final.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return 0 if all(v['passed'] for v in summary.values()) else 1


if __name__=='__main__':raise SystemExit(main())

~~~

【补全内容（relay_additions/verify_final.py）止】

## relay_additions/source-links.js

【补全内容（relay_additions/source-links.js）起】

~~~js
(function(global){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function links(value){
    const citations=(value?.results||[]).filter(r=>r.tool==='knowledge').flatMap(r=>r.result?.citations||[]);
    const safe=citations.filter(c=>typeof c.citation_uri==='string' && /^\/(?:review\/source\/[a-zA-Z0-9_-]+|relay\/source\/[a-zA-Z0-9_-]{1,100}\/[a-zA-Z0-9_-]{1,100})#L\d+$/.test(c.citation_uri));
    return safe.length?'<section class="agent-result-card"><h4>核对引用原文</h4>'+safe.map(c=>'<p><a data-review-source href="'+esc(c.citation_uri)+'" target="_blank" rel="noopener noreferrer">'+esc(c.title)+' · 第 '+esc(c.start_line)+' 行</a></p>').join('')+'</section>':'';
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={links};return;}
  function install(){
    const view=global.BankCustomerView;if(!view||view.reviewLinksInstalled)return;
    const original=view.render;view.render=value=>original(value)+links(value);view.reviewLinksInstalled=true;
  }
  install();global.addEventListener('bank-ready',install);
})(globalThis);

~~~

【补全内容（relay_additions/source-links.js）止】

## relay_additions/experience-layout.css

【补全内容（relay_additions/experience-layout.css）起】

~~~css
/* Keep the summary control above existing service shortcuts and trade bar. */
#experience-launcher{bottom:calc(78px + env(safe-area-inset-bottom, 0px))}
@media(max-width:650px){#experience-launcher{bottom:calc(78px + env(safe-area-inset-bottom, 0px));right:14px}}

~~~

【补全内容（relay_additions/experience-layout.css）止】

## relay_additions/test_frontend.cjs

【补全内容（relay_additions/test_frontend.cjs）起】

~~~cjs
const assert = require('node:assert/strict');
const {links} = require('./source-links.js');
const render=uri=>links({results:[{tool:'knowledge',result:{citations:[{citation_uri:uri,title:'<安全>',start_line:12}]}}]});
assert.match(render('/relay/source/release-1/yuki-01#L12'), /&lt;安全&gt;/);
assert.match(render('/review/source/yuki-01#L12'), /noopener noreferrer/);
for(const uri of ['https://evil.test/','javascript:alert(1)','/relay/source/v/../../runtime/db','/relay/source/v/doc#L12?x=1']) assert.equal(render(uri),'');
console.log(JSON.stringify({passed:true,checks:6}));

~~~

【补全内容（relay_additions/test_frontend.cjs）止】

## start_relay.py

【补全内容（start_relay.py）起】

~~~py
"""1030 additive continuation; Python UTF-8 mode is enabled by the launcher."""
import argparse
from pathlib import Path
from start import prepare_node


def main():
    prepare_node()
    from relay_additions.runtime import RelayService, make_server
    parser = argparse.ArgumentParser(description='启动1030接力验收版')
    parser.add_argument('--port', type=int, default=8803)
    parser.add_argument('--db', default=str(Path(__file__).parent / 'runtime/relay.sqlite3'))
    parser.add_argument('--review-db', help='启用已审核知识模式；无发布版本则拒答')
    args = parser.parse_args()
    service = RelayService(args.db, review_db=args.review_db)
    app = make_server(service, port=args.port)
    print(f'1030接力验收版：http://127.0.0.1:{app.server_port}/', flush=True)
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.server_close()


if __name__ == '__main__':
    main()

~~~

【补全内容（start_relay.py）止】

## 启动1030接力验收版.bat

【补全内容（启动1030接力验收版.bat）起】

~~~bat
@echo off
cd /d "%~dp0"
python -X utf8 start_relay.py %*
pause

~~~

【补全内容（启动1030接力验收版.bat）止】
