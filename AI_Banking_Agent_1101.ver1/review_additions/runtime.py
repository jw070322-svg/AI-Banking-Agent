"""Opt-in application composition, restricted HTTP additions and safe citations."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4, uuid5, NAMESPACE_URL
import hashlib
import json
import re
import unicodedata

from first_agent.service import AgentService, Fault, BASE, METHODS
from first_agent.rag_additions import AdditiveRAGService
from first_agent import server as legacy_server, extensions
from first_agent.vendor.rag.retrieval import tokenize
from .experience import ExperienceStore, RESULTS, strict
from .web_security import WebSecurity
from .audit_chain import AuditChain
from .ledger_gateway import LedgerGateway

VERSION = 'AI_Banking_Agent_1029_rag_review'
ROOT = Path(__file__).parent

def explanatory_excerpt(evidence, question):
    """Avoid presenting example user questions as if they were an answer."""
    if '常见问题' in evidence.get('section', ''):
        return ''
    query=set(tokenize(question)); candidates=[]; in_user_example=False
    for i, line in enumerate(evidence['text'].splitlines()):
        text=line.strip().lstrip('- ').strip()
        if re.match(r'用户(?:说|问题|提问)[：:]', text):
            in_user_example=True;continue
        if re.match(r'AI.{0,8}(?:提示|判断|建议|回答|说明|解释|提醒)[：:]', text):
            in_user_example=False;continue
        if in_user_example or not text or text.startswith('#') or text.endswith(('：',':','？','?')):
            continue
        if re.match(r'为什么|怎么|如何|是否|能不能|可不可以|什么是|以下问题',text):
            continue
        if len(text)<10 or re.fullmatch(r'[-|\s:]+',text):
            continue
        candidates.append((len(query & set(tokenize(text))),i,line))
    selected=sorted(sorted(candidates,key=lambda item:(-item[0],item[1]))[:3],key=lambda item:item[1])
    excerpt='\n'.join(line for _,_,line in selected)
    return excerpt[:900] if excerpt else ''

def knowledge_boundary(question):
    """Conservative routing for explicit commands, not a claim of complete NLU/DLP."""
    if not isinstance(question, str):
        return None
    text = unicodedata.normalize('NFKC', question)
    other = r'别人|他人|另一个用户|其他客户|某人|对方|朋友|同事|家人'
    records = r'账单|流水|账户|余额|身份证|手机号|银行卡|转账记录|交易记录|财务信息'
    command = r'查|看一下|告诉我|给我|汇总|发给|获取|拿到|调用|判断|分析'
    # General discussion of why these requests are forbidden remains educational.
    educational = bool(re.search(r'为什么不能|为何不能|如何防止|怎么防止|应该如何拒绝|该怎么拒绝', text))
    if not educational and re.search(other, text) and re.search(records, text) and re.search(command, text):
        return '不能查询或判断他人的私人账户信息。查询本人资料，请进入账户或账单页面并核对授权。'
    if not educational and re.search(r'忽略.{0,8}(规则|安全)|绕过.{0,12}(确认|权限|审核)|不用.{0,8}确认|不需要.{0,8}(确认|审核)', text):
        return '金融操作需要核对对象、金额和授权，并完成必要确认。知识问答不能代替这些步骤。'
    if re.search(r'(把|将|直接).*(客户|账户|内部风险).*(发给|发送|外发).*(外部|模型)|汇总后发给我', text):
        return '不能通过知识问答导出客户资料或内部风险信息；需要核对数据用途、范围与授权。'
    return None

class ReviewRAG:
    def __init__(self, primary):
        self.live_knowledge = None
        self.primary = AdditiveRAGService(primary)
        self.retriever = self.primary.retriever
        self.client = self.primary.client

    def search(self, *args, **kwargs):
        return self.primary.search(*args, **kwargs)

    def ask(self, question, top_k=4, **kwargs):
        if self.live_knowledge is not None:
            return self.live_knowledge.ask(question, top_k, **kwargs)
        # Validate before guarding so type/size limits cannot be bypassed.
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise ValueError('问题需要1至2000个字符')
        if type(top_k) is not int or not 1 <= top_k <= 10:
            raise ValueError('top_k必须为1至10')
        reason = knowledge_boundary(question)
        if reason:
            return {'schema_version': 1, 'status': 'boundary_rejected', 'answer': reason,
                    'evidence': [], 'citations': [], 'tool_calls': [], 'warnings': [],
                    'generation_mode': 'deterministic_boundary', 'retrieval_mode': 'not_run'}
        normalized = unicodedata.normalize('NFKC', question)
        personal_suitability = re.search(r'(?:我|本人).{0,10}(?:是否适合|适不适合|适合这|能拿到授信|能获得授信)', normalized)
        personal_risk = re.search(r'(?:你说我|判断我|认定我).{0,20}(?:风险|健康|异常)', normalized)
        if personal_suitability or personal_risk:
            return {'schema_version': 1, 'status': 'needs_business_data',
                    'answer': '这需要核对你的实际资料，通用知识不能直接给出个人结论。理财请先核对风险档案、产品、金额和用款期限；账户风险请查看已授权账单与具体提示。企业授信需要相应业务人员核查。',
                    'evidence': [], 'citations': [], 'tool_calls': [], 'warnings': [],
                    'generation_mode': 'deterministic_routing', 'retrieval_mode': 'not_run'}
        result = self.primary.ask(question, top_k, **kwargs)
        if result.get('status')=='grounded' and result.get('generation_mode') in {'extractive','extractive_fallback'}:
            selected=[];parts=[]
            for item in result.get('evidence',[]):
                excerpt=explanatory_excerpt(item,question)
                if excerpt:
                    selected.append(item)
                    parts.append('['+item['citation_id']+'] '+item.get('section',item['title'])+'\n'+excerpt)
            if selected:
                result={**result,'answer':'以下为资料中的解释与处理建议，请结合实际情况核对：\n\n'+'\n\n'.join(parts),
                        'evidence':selected,'citations':[self.primary.primary._citation(e) for e in selected]}
            else:
                result={**result,'status':'insufficient_evidence',
                        'answer':'只找到相似的提问或过短的片段，尚不足以形成解释。请补充具体资料，或在对应业务页面核对。',
                        'evidence':[],'citations':[]}
        # Keep provenance and hash; give the local UI a usable source link.
        for item in result.get('evidence', []) + result.get('citations', []):
            item['original_citation_uri'] = item.get('citation_uri')
            item['citation_uri'] = '/review/source/' + item['document_id'] + '#L' + str(item['start_line'])
        return result

KNOWN_ACTIONS = set(extensions.ACTIONS) | {'snapshot', 'accounts', 'transactions', 'subscriptions',
    'recommend', 'events', 'analysis', 'analysis.status', 'operation', 'audit.export',
    'chat', 'knowledge', 'rpc', 'scenario.generate', 'recipients', 'transfer.preview',
    'transfer.verify', 'transfer.confirm', 'transfer.reconcile', 'transfer.cancel',
    'external.status', 'external.probe', 'external.search', 'local_life.links'}

class ReviewService(AgentService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rag = ReviewRAG(self.rag)
        self.experience = ExperienceStore(self)
        self.web_security = WebSecurity()
        self.audit_chain = AuditChain(self)
        self.ledger_gateway = LedgerGateway(self, KNOWN_ACTIONS)

    def dispatch(self, db, state, action, args):
        # Same ledger transaction; check precedes any mutation.
        return self.ledger_gateway.execute(db, state, action, args, super().dispatch)

    def research_call(self, sid, action, args, key=None):
        from contextlib import closing
        with closing(self.connect()) as db:
            state = self.load(db, sid)
        try:
            self.web_security.check(state, action, args)
        except Fault as exc:
            with self.transaction() as db:
                self.audit(db, sid, action, 'rejected', {})
            return self.envelope(status='rejected', error={'code':exc.code,'message':exc.message})
        if action == 'knowledge' and self.rag.live_knowledge is not None:
            self.require(state, 'knowledge')
            try:
                result = self.rag.ask(args.get('question',''), args.get('top_k',3))
                response = self.envelope(result)
            except (Fault, ValueError) as exc:
                response = self.envelope(status='rejected', error={'code':getattr(exc,'code','INVALID_ARGUMENT'),
                    'message':getattr(exc,'message',str(exc))})
            with self.transaction() as db:
                self.audit(db, sid, action, response['status'], {})
            return response
        return super().research_call(sid, action, args, key)

    def audit(self, db, sid, action, status, detail):
        # Existing audit UI needs the result and correlation, not arbitrary args,
        # OTPs, prompts, error echoes or returned financial records.
        if hasattr(self, 'audit_chain'):
            self.audit_chain.verify(db)
        safe = {'summary_only': True}
        if isinstance(detail, dict):
            request_id = detail.get('request_id')
            if isinstance(request_id, str) and re.fullmatch(r'[a-f0-9]{32}', request_id):
                safe['request_id'] = request_id
            args = detail.get('arguments')
            if isinstance(args, dict) and args.get('method') in METHODS:
                safe['method'] = args['method']
        super().audit(db, sid, action if action in KNOWN_ACTIONS | {'session.create', 'developer.reset', 'developer.restore'} else 'other',
                      status if status in RESULTS else 'unknown', safe)
        if hasattr(self, 'audit_chain'):
            self.audit_chain.append(db)

    def call(self, sid, action, args=None, key=None):
        pref = None
        record_warning = False
        label = action if action in KNOWN_ACTIONS else 'other'
        if action == 'rpc' and isinstance(args, dict) and args.get('method') in METHODS:
            label = 'rpc.' + args['method']
        attempt = str(uuid4())
        try:
            pref = self.experience.status(sid)
            self.experience.server_event(sid, attempt, label, 'started', 'request_started', epoch=pref['epoch'])
        except Exception:
            record_warning = True
        try:
            response = super().call(sid, action, args, key)
        except Exception as exc:
            # No exception details in the experience table. An exception alone
            # cannot establish that a remote payment has failed.
            if pref:
                try:
                    failure_event = str(uuid4())
                    self.experience.server_event(sid, failure_event, label,
                        'rejected' if isinstance(exc, Fault) else 'unknown', 'request_result', attempt, pref['epoch'])
                    self.experience.link_result(sid, attempt, failure_event, pref['epoch'])
                except Exception:
                    pass
            raise
        result = response.get('data')
        status = response.get('status', 'unknown')
        if isinstance(result, dict) and result.get('status') in RESULTS:
            status = result['status']
        result_id = response.get('request_id', attempt)
        event_id = str(uuid5(NAMESPACE_URL, sid + ':' + result_id))
        try:
            if pref:
                self.experience.server_event(sid, event_id, label, status, 'request_result', result_id, pref['epoch'])
                self.experience.link_result(sid, attempt, event_id, pref['epoch'])
        except Exception:
            # Never turn a committed transaction into an apparent failed payment
            # just because optional experience storage is unavailable.
            record_warning = True
        if record_warning:
            response = dict(response)
            response['experience_warning'] = '操作结果已返回，但摘要未同步；请以任务回执为准'
        return response

def source_document(service, doc_id):
    doc = service.rag.retriever.documents.get(doc_id)
    if not doc:
        raise Fault('NOT_FOUND', '资料不存在', 404)
    path = (BASE / 'knowledge' / doc['path']).resolve()
    if not path.is_relative_to((BASE / 'knowledge').resolve()) or not path.is_file():
        raise Fault('SOURCE_MISSING', '原始资料暂不可用', 404)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != doc['sha256']:
        raise Fault('SOURCE_CHANGED', '资料已变化，需重新核验引用', 409)
    return doc, raw

def make_server(service, host='127.0.0.1', port=8802):
    legacy_server.APP_VERSION = VERSION
    legacy_server.SESSION_COOKIE = 'banking_review_1029'
    server = legacy_server.make_server(service, host, port)
    OriginalHandler = server.RequestHandlerClass

    class Handler(OriginalHandler):
        def send_bytes(self, raw, content_type):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers(); self.wfile.write(raw)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path not in {'/', '/index.html', '/review/experience.js', '/review/source-links.js', '/review/experience.css', '/api/experience/status'} and not path.startswith('/review/source/'):
                return super().do_GET()
            try:
                self.safe_host()
                if path == '/api/experience/status':
                    return self.send_json(service.envelope(service.experience.status(self.sid())))
                if path in {'/', '/index.html'}:
                    raw = (BASE / 'web/index.html').read_bytes()
                    hook = b'<link rel="stylesheet" href="/review/experience.css"><script defer src="/review/source-links.js"></script><script defer src="/review/experience.js"></script>'
                    return self.send_bytes(raw.replace(b'</head>', hook + b'</head>', 1), 'text/html; charset=utf-8')
                if path.startswith('/review/source/'):
                    import html
                    with service.transaction() as db:
                        service.load(db, self.sid())
                    doc, raw = source_document(service, path.rsplit('/', 1)[1])
                    lines = ''.join('<div id="L%d"><small>%d</small> %s</div>' % (i, i, html.escape(line)) for i, line in enumerate(raw.decode('utf-8-sig').splitlines(), 1))
                    page = '<!doctype html><meta charset="utf-8"><title>参考资料</title><style>body{max-width:900px;margin:40px auto;font:16px/1.8 system-ui;padding:20px;color:#142745}small{color:#64748b}div:target{background:#e3edff}pre{white-space:pre-wrap}</style><h1>' + html.escape(doc['title']) + '</h1><p>项目演示资料。引用可以追溯，不代表实时银行条款或业务已实现。</p><pre>' + lines + '</pre>'
                    return self.send_bytes(page.encode(), 'text/html; charset=utf-8')
                asset = ROOT / path.rsplit('/', 1)[1]
                return self.send_bytes(asset.read_bytes(), 'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
            except Fault as exc:
                self.send_json(service.envelope(status='rejected', error={'code': exc.code, 'message': exc.message}), exc.status)

        def do_POST(self):
            path = urlsplit(self.path).path
            if not path.startswith('/api/experience/'):
                return super().do_POST()
            try:
                self.safe_host()
                if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                    raise Fault('CONTENT_TYPE', '需要JSON格式请求', 415)
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384:
                    raise Fault('PAYLOAD_SIZE', '记录请求过大', 413)
                def pairs(items):
                    obj = {}
                    for key, value in items:
                        if key in obj: raise ValueError('duplicate key')
                        obj[key] = value
                    return obj
                body = json.loads(self.rfile.read(size), object_pairs_hook=pairs,
                                  parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                routes = {'consent': service.experience.consent, 'events': service.experience.ingest,
                          'query': service.experience.query, 'feedback': service.experience.feedback,
                          'delete': service.experience.delete}
                fn = routes.get(path.rsplit('/', 1)[1])
                if not fn: raise Fault('NOT_FOUND', '接口不存在', 404)
                return self.send_json(service.envelope(fn(self.sid(), body)))
            except Fault as exc:
                self.send_json(service.envelope(status='rejected', error={'code': exc.code, 'message': exc.message}), exc.status)
            except (ValueError, TypeError):
                self.send_json(service.envelope(status='rejected', error={'code': 'INVALID_JSON', 'message': '记录格式不正确'}), 400)
            except Exception:
                self.send_json(service.envelope(status='failed', error={'code': 'EXPERIENCE_UNAVAILABLE', 'message': '摘要服务暂不可用；请稍后重试，交易状态请查看任务回执'}), 503)

    server.RequestHandlerClass = Handler
    return server
