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
