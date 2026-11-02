"""Single persisted demo ledger. All state changes and receipts commit together."""
from __future__ import annotations
from contextlib import contextmanager, closing
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import hashlib, json, re, shutil, sqlite3, subprocess, time
from threading import Lock
from .external_services import ExternalServices
from .local_wind import load_local_wind
from . import finance_lexicon, online_verification

from .security import Scanner
from . import extensions
from .intent_parser import PARSER_VERSION, parse_transfer
from .recipients import DIRECTORY_VERSION, contacts_for, default_directory
from .analysis_bridge import (AnalysisError, analysis_status, generate_scenario,
                              run_analysis_tool, session_to_scenario, session_context, _load_modules)
from .vendor.eva.data import MockBank, D, POLICY
from .vendor.eva.models import ToolError
from .vendor.eva.tools import ToolRegistry
from .vendor.eva.risk.auth import StepUpAssertion
from .vendor.finance.rule_driven import recommend
from .vendor.rag.corpus import build_index
from .vendor.rag.service import RAGService
from .vendor.security.gate import Principal, ToolPolicy, SecurityGate

BASE=Path(__file__).resolve().parents[1]
SCHEMA='1.0.0'
POLICY_VERSION='integrated-demo-1026.1'
METHODS={'configureSimulation','assistant','authorize','configure','select','setProfile','analyze','summary','reviewSubscription','keep','budget','propose','cancel','verify','execute','reconcile','settle','settleCard','advance','pause','resume','unlock','liquid','projection','interpret','eligibility','total','capacity','monthlySaved'}
READ={'analyze','summary','reviewSubscription','keep','reconcile','settle','settleCard'}

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return 'sha256:'+hashlib.sha256(canonical(value).encode()).hexdigest()
def stamp():return datetime.now(timezone.utc).isoformat()
def integer(value,minimum=0):
    if type(value) is not int or not minimum<=value<=1_000_000_000:
        raise Fault('INVALID_ARGUMENT','金额必须为范围内的整数分')
    return value

class Fault(Exception):
    def __init__(self,code,message,status=400):self.code,self.message,self.status=code,message,status

class AgentService:
    def __init__(self,db_path=None,clock=time.time):
        self.db_path=Path(db_path or BASE/'runtime/agent.sqlite3')
        self.db_path.parent.mkdir(parents=True,exist_ok=True)
        self.clock=clock; self.scanner=Scanner()
        self.recipient_records=default_directory()
        self.node=shutil.which('node')
        if not self.node:raise RuntimeError('Node.js is required for the teammate business engine')
        with closing(self.connect()) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS sessions(sid TEXT PRIMARY KEY,state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests(sid TEXT,key TEXT,hash TEXT,response TEXT,PRIMARY KEY(sid,key));
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,sid TEXT,at TEXT,action TEXT,status TEXT,detail TEXT);''')
        index=BASE/'knowledge/index.json'
        if not index.exists():build_index(BASE/'knowledge/manifest.json',index)
        self.rag=RAGService(index)
        self.external=ExternalServices()
        self.market_data,self.market_load_error=load_local_wind()
        self.research_lock=Lock()
        self.research_cache={}
        with closing(self.connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS research_requests(sid TEXT,key TEXT,hash TEXT,response TEXT,PRIMARY KEY(sid,key))')
        self.gate=SecurityGate({n:ToolPolicy(scope,'write' if n=='transfer' else 'read') for n,scope in {
            'accounts':'account:read','transactions':'transactions:read','subscriptions':'subscriptions:read',
            'transfer':'transfer:write','recommend':'products:read','knowledge':'knowledge:read'}.items()},POLICY_VERSION)

    def connect(self):
        db=sqlite3.connect(self.db_path,timeout=20,isolation_level=None)
        db.execute('PRAGMA journal_mode=WAL'); return db

    @contextmanager
    def transaction(self):
        db=self.connect()
        try:
            db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def engine(self,state=None,method=None,args=None):
        proc=subprocess.run([self.node,str(BASE/'first_agent/engine_worker.cjs')],input=canonical({'state':({k:v for k,v in state.items() if k!='market_data'} if state else None),'method':method,'args':args or [],'now':self.clock()}),
                            text=True,encoding='utf-8',capture_output=True,timeout=15,cwd=BASE)
        if proc.returncode:raise Fault('ENGINE_FAILURE','业务引擎运行失败',500)
        result=json.loads(proc.stdout)
        if state and 'market_data' in state: result['state']['market_data']=state['market_data']
        return result

    def create_session(self):
        sid=uuid4().hex+uuid4().hex
        state=self.engine()['state']; state.update(customer_id='CUST-001',session_id=sid,transfer_ops=[],daily_transfers={},task_log=[],clarification=None,chat_draft_id=None)
        state['contacts']=contacts_for(self.recipient_records,state['customer_id'])
        state['recipient_directory_version']=DIRECTORY_VERSION
        with self.transaction() as db:
            db.execute('INSERT INTO sessions VALUES(?,?)',(sid,canonical(state)))
            self.audit(db,sid,'session.create','succeeded',{'simulated':True})
        return sid

    def load(self,db,sid):
        row=db.execute('SELECT state FROM sessions WHERE sid=?',(sid,)).fetchone()
        if not row:raise Fault('AUTH_REQUIRED','演示会话不存在，请重新进入',401)
        state=json.loads(row[0])
        if 'cards' not in state or 'simulation' not in state:
            state=self.engine(state)['state']
            for op in state['operations']+state['transfer_ops']:
                if op['status']=='awaiting_confirmation':op['status']='invalidated'
        state['contacts']=contacts_for(self.recipient_records,state['customer_id'])
        state['recipient_directory_version']=DIRECTORY_VERSION
        return state

    def resolve_recipient(self,state,name=None,recipient_id=None):
        records=[r for r in self.recipient_records if r['customer_id']==state['customer_id']]
        if recipient_id is not None:
            matches=[r for r in records if r['beneficiary_id']==recipient_id]
            if name is not None and matches and matches[0]['name']!=name:
                raise Fault('RECIPIENT_MISMATCH','收款人编号和姓名不一致，请重新选择')
        else:
            matches=[r for r in records if isinstance(name,str) and r['name']==name.strip()]
        if not matches:raise Fault('RECIPIENT_NOT_FOUND','未在当前演示收款人名册中找到该姓名，请从转账表单选择收款人')
        if len(matches)!=1:raise Fault('RECIPIENT_AMBIGUOUS','存在同名收款人，请在转账表单中选择具体收款人')
        return deepcopy(matches[0])

    def require_recipient(self,state,recipient_id):
        recipient=self.resolve_recipient(state,recipient_id=recipient_id)
        if not recipient['whitelisted']:raise Fault('POLICY_DENIED','收款人未在安全名册准入，暂不支持转出')
        return recipient

    def audit(self,db,sid,action,status,detail):
        db.execute('INSERT INTO audit(sid,at,action,status,detail) VALUES(?,?,?,?,?)',
                   (sid,stamp(),action,status,canonical(self.scanner.redact_obj(detail))))

    def envelope(self,result=None,status='succeeded',error=None,trace=None):
        return {'schema_version':SCHEMA,'request_id':uuid4().hex,'status':status,'data':result,
                'error':error,'trace':trace or [],'simulated':True}

    def require(self,state,tool):
        if state.get('consentExpiresAt') and self.clock()*1000>=state['consentExpiresAt']:raise Fault('SCOPE_EXPIRED','演示授权已过期')
        scopes={'knowledge:read','products:read'}
        if state['consent']['read']:scopes.update({'account:read','transactions:read','subscriptions:read'})
        if state['consent']['trade']:scopes.add('transfer:write')
        principal=Principal(state['customer_id'],frozenset(scopes),frozenset({state['customer_id']}))
        decision=self.gate.check(principal,tool,state['customer_id'])
        if decision.decision!='pass' and not (tool=='transfer' and decision.decision=='review'):
            raise Fault('SCOPE_DENIED','缺少对应演示权限',403)

    def call(self,sid,action,args=None,key=None):
        if action in {'knowledge','external.status','external.probe','external.search','local_life.links'}:
            return self.research_call(sid,action,args or {},key)
        response=self._call_local(sid,action,args,key)
        if action=='chat' and not response.get('error'):
            results=(response.get('data') or {}).get('results',[])
            if len(results)==1 and results[0].get('tool')=='knowledge':
                result=self.research_call(sid,'knowledge',{'question':(args or {}).get('message','')},('chat:'+digest(key)) if key else None)
                if result.get('error'): return result
                response['data']['results'][0]['result']=result['data']
                response['data']['conclusion']='已完成知识检索，请核对来源和 AI 生成标识。'
        return response

    def research_call(self,sid,action,args,key=None):
        """Network/model reads run without holding the banking SQLite write lock."""
        if not isinstance(args,dict): raise Fault('INVALID_ARGUMENT','参数应为对象')
        if key is not None and (not isinstance(key,str) or not 1<=len(key)<=128): raise Fault('INVALID_ARGUMENT','无效幂等键')
        request_hash=digest({'action':action,'args':args})
        with self.research_lock:
            with closing(self.connect()) as db:
                state=self.load(db,sid); self.require(state,'knowledge')
            now=time.monotonic()
            self.research_cache={k:v for k,v in self.research_cache.items() if now-v[2]<120}
            old=self.research_cache.get((sid,key)) if key else None
            if old:
                if old[0]!=request_hash: raise Fault('IDEMPOTENCY_CONFLICT','同一幂等键不能提交不同参数',409)
                return deepcopy(old[1])
            try:
                if action=='external.status': result=self.external.status()
                elif action=='external.probe': result=self.external.probe()
                elif action=='local_life.links': result=self.external.links(args.get('city',''),args.get('category','餐厅'))
                elif action=='external.search':
                    if set(args)!={'question','public_search_approved'} or args.get('public_search_approved') is not True:
                        raise Fault('SEARCH_APPROVAL_REQUIRED','请确认本次问题是可公开发送的通用问题后再搜索',403)
                    text=args.get('question','')
                    if self.scanner.scan_input(text).injection_suspected: raise Fault('INJECTION_BLOCKED','不接受绕过授权的指令')
                    result=self.external.baidu(text)
                else:
                    question=args.get('question','')
                    if not isinstance(question,str): raise ValueError()
                    if self.scanner.scan_input(question).injection_suspected: raise Fault('INJECTION_BLOCKED','不接受绕过授权的指令')
                    result=finance_lexicon.answer(question) or self.rag.ask(question,args.get('top_k',3))
                    prefix=re.match(r'^(?:请问|请)?(?:什么是|什么叫|解释一下|解释|介绍一下)(.+?)[？?。\s]*$',question)
                    suffix=re.match(r'^(?:请问)?(.+?)(?:是什么意思|是什么|什么意思)[？?。\s]*$',question)
                    subject=(prefix or suffix).group(1).strip() if prefix or suffix else ''
                    if result.get('evidence') and len(subject)>=2 and not any(subject in e.get('text','') for e in result['evidence']):
                        result={**result,'status':'no_evidence','citations':[],'evidence':[]}
                    # 官方原文核验：只有本次请求显式传 online_verify=True 才发往外网。
                    # 优先级：官方原文 > 模型补充解释 > 只有线索。
                    if result.get('status')=='no_evidence' and args.get('online_verify') is True:
                        checked=online_verification.verify(question)
                        if checked.get('status') in ('verified','partial'):
                            result=checked
                        else:
                            result={**result,'online_verification':checked}
                    if result.get('status')=='no_evidence':
                        checked=result.get('online_verification')
                        result=self.external.fallback(question,result,args.get('public_search_approved') is True)
                        if checked:
                            # 如实记录官方原文这一环也试过（并说明为什么没用上）。
                            result.setdefault('fallback_steps',[]).insert(-1,{'provider':'official_web','status':checked.get('status')})
                            result['online_verification']=checked
                    result['risk_notice']='通用知识说明；AI 补充内容未经外部事实核验，不作为金融操作依据'
                response=self.envelope(result)
            except ValueError as exc:
                response=self.envelope(status='rejected',error={'code':'INVALID_ARGUMENT','message':str(exc) or '参数无效'})
            except Fault as exc:
                response=self.envelope(status='rejected',error={'code':exc.code,'message':exc.message})
            with self.transaction() as db:
                safe_args={k:v for k,v in args.items() if k!='question'}
                # 只记同意与否，不记问题原文（沿用既有审计口径）。
                if action=='knowledge': safe_args['online_verify']=args.get('online_verify') is True
                if 'question' in args: safe_args['question_length']=len(args['question']) if isinstance(args['question'],str) else None
                self.audit(db,sid,action,response['status'],{'arguments':safe_args,
                    'output':{'status':(response.get('data') or {}).get('status'), 'fallback_steps':(response.get('data') or {}).get('fallback_steps'), 'error':response.get('error')},
                    'risk_check':'public_query_filter_is_not_complete_DLP; no_bank_state_or_paid_api',
                    'approval':('explicit_public_search' if args.get('public_search_approved') is True else 'not_granted') if action in ('external.search','knowledge') else 'local_or_fixed_probe'})
            if key:
                if len(self.research_cache)>=64: self.research_cache.pop(next(iter(self.research_cache)))
                self.research_cache[(sid,key)]=(request_hash,deepcopy(response),time.monotonic())
            return response

    def authorize_cached_response(self,db,state,action,args,response):
        from .replay_access import check_replay_access
        check_replay_access(self,state,action,args,response)
        return response

    def _call_local(self,sid,action,args=None,key=None):
        args={} if args is None else args
        try: request_hash=digest({'action':action,'args':args})
        except (ValueError,TypeError):return self.envelope(error={'code':'INVALID_ARGUMENT','message':'参数无法规范化'},status='rejected')
        with self.transaction() as db:
            state=self.load(db,sid)
            if key:
                if not isinstance(key,str) or not 1<=len(key)<=128:raise Fault('INVALID_ARGUMENT','无效幂等键')
                old=db.execute('SELECT hash,response FROM requests WHERE sid=? AND key=?',(sid,key)).fetchone()
                if old:
                    if old[0]!=request_hash:raise Fault('IDEMPOTENCY_CONFLICT','同一幂等键不能提交不同参数',409)
                    try:
                        return self.authorize_cached_response(db,state,action,args,json.loads(old[1]))
                    except Fault as exc:
                        response=self.envelope(status='rejected',error={'code':exc.code,'message':exc.message})
                        self.audit(db,sid,action,'rejected',{'cache_replay':True,'error':{'code':exc.code}})
                        return response
            previous=deepcopy(state)
            try:
                result=self.dispatch(db,state,action,args)
                status=(result.pop('_status',result.get('status','succeeded')) if isinstance(result,dict) else 'succeeded')
                if status not in {'succeeded','awaiting_confirmation','needs_input','unknown','processing','failed','cancelled','invalidated'}:status='succeeded'
                response=self.envelope(result,status)
            except (Fault,ToolError) as exc:
                if not getattr(exc,'persist',False):state=previous
                response=self.envelope(status='rejected',error={'code':exc.code,'message':self.scanner.redact_text(getattr(exc,'message',str(exc)))})
            except (TypeError,ValueError,KeyError,IndexError) as exc:
                state=previous
                response=self.envelope(status='rejected',error={'code':'INVALID_ARGUMENT','message':'参数类型、数量或内容不符合接口约定'})
            detail={'request_hash':request_hash,'request_id':response['request_id'],'arguments':args,'error':response['error']}
            if action=='chat': detail['arguments']={'message_length':len(args.get('message','')) if isinstance(args.get('message'),str) else None}
            if action=='rpc' and args.get('method')=='assistant': detail['arguments']={'method':'assistant','message_length':len(args.get('args',[None])[0]) if args.get('args') and isinstance(args['args'][0],str) else None}
            if action=='chat' or (action=='rpc' and args.get('method')=='assistant'):
                data=response.get('data') or {}
                detail.update(parser_version=PARSER_VERSION,directory_version=DIRECTORY_VERSION,
                              intent=data.get('intent'),
                              reason_code=data.get('reason_code') or (response['error'] or {}).get('code'),
                              speech_act=(data.get('candidate') or {}).get('speech_act'),
                              missing=data.get('missing',[]))
            if 'content_base64' in detail.get('arguments',{}):
                detail['arguments']={k:v for k,v in args.items() if k!='content_base64'}
                detail['arguments']['encoded_length']=len(args.get('content_base64',''))
            value=response.get('data')
            detail['output']={'status':response['status'],'error':response['error'],'fields':list(value) if isinstance(value,dict) else [],'conclusion':value.get('conclusion') if isinstance(value,dict) else None}
            if action=='chat' or (action=='rpc' and args.get('method')=='assistant'):
                detail.pop('request_hash',None)
                detail['output']['conclusion']=None
            detail['risk_check']='passed_local_policy' if not response['error'] else response['error']['code']
            detail['approval']='explicit_operation_confirmation' if action=='transfer.confirm' or (action=='rpc' and args.get('method')=='execute') else 'user_requested_local_configuration' if action in {'calendar.reserve','calendar.release','calendar.save','profile.update','market.import'} else 'read_only_or_existing_workflow'
            self.audit(db,sid,action,response['status'],detail)
            db.execute('UPDATE sessions SET state=? WHERE sid=?',(canonical(state),sid))
            if key:db.execute('INSERT INTO requests VALUES(?,?,?,?)',(sid,key,request_hash,canonical(response)))
            return response

    def pending(self,state,op_id):
        for op in state['operations']+state['transfer_ops']:
            if op['id']==op_id:return op
        raise Fault('NOT_FOUND','未找到当前会话的操作',404)

    def bound_hash(self,state,op):
        # Explicit canonical binding shared by preview, assertion, commit and audit.
        return digest({'user_id':state['customer_id'],'session_id':state['session_id'],
                       'operation_id':op['id'],'type':op['type'],'target':op['target'],'amount_minor':op['amount'],
                       'version':op['version'],'card_id':op.get('cardId','CARD-DEBIT' if op['type']=='transfer' else None),
                       'policy_version':POLICY_VERSION,'expires_at':op['expires_at']})

    def attach(self,state,op):
        op['expires_at']=int(self.clock())+300;op['policy_version']=POLICY_VERSION
        op['preview_hash']=self.bound_hash(state,op)
        return deepcopy(op)

    def check_pending(self,state,op):
        if op['status']!='awaiting_confirmation':raise Fault('INVALID_STATE','操作已提交、取消或失效')
        if self.clock()>=op.get('expires_at',0):
            op['status']='invalidated';e=Fault('PREVIEW_EXPIRED','预览已过期，请重新生成');e.persist=True;raise e
        if op['version']!=state['version'] or op.get('preview_hash')!=self.bound_hash(state,op):
            raise Fault('PREVIEW_STALE','参数、权限或账本已变化，请重新预览')
        if op.get('policy_version')!=POLICY_VERSION:raise Fault('POLICY_CHANGED','策略已变化，请重新预览')

    def engine_call(self,state,method,args):
        response=self.engine(state,method,args)
        state.clear();state.update(response['state'])
        if response['error']:
            e=Fault('POLICY_DENIED',response['error']);e.persist=True;raise e
        return response['result']

    def invalidate_transfers(self,state):
        for op in state['transfer_ops']:
            if op['status']=='awaiting_confirmation' and op['version']!=state['version']:op['status']='invalidated'

    def dispatch(self,db,state,action,args):
        if action in extensions.ACTIONS:return extensions.dispatch(self,db,state,action,args)
        if action=='scenario.generate':
            allowed={'requirement','prompt','format','scenario_type','seed','reference_date'}
            if set(args)-allowed:raise Fault('INVALID_ARGUMENT','不支持的场景参数；对客接口不接受评测开关')
            legacy=args.get('format','contract' if 'prompt' in args else 'legacy')=='legacy'
            if args.get('format','legacy') not in {'legacy','contract'}:raise Fault('INVALID_ARGUMENT','format 必须为 legacy 或 contract')
            if 'prompt' in args and 'requirement' in args and args['prompt']!=args['requirement']:
                raise Fault('INVALID_ARGUMENT','prompt 与 requirement 不一致')
            try:
                scenario=generate_scenario(args.get('prompt',args.get('requirement')),args.get('scenario_type'),args.get('seed'),args.get('reference_date'))
            except AnalysisError as exc:
                code='SCENARIO_INVALID' if legacy and exc.code=='SCENARIO_UNSUPPORTED' else exc.code
                raise Fault(code,exc.message) from exc
            if not legacy:return scenario
            # Compatibility projection only; canonical generation/validation stays upstream.
            return {'schema_version':'scenario-1.0','scenario_id':scenario['scenario_id'],
                    'scenario_type':scenario['scenario_type'],'accounts':scenario['accounts'],
                    'transactions':[{'id':t['transaction_id'],'account_id':t['account_id'],'date':t['date'],
                                     'amount_minor':t['amount'],'category':t['category'],'status':t['status']} for t in scenario['transactions']],
                    'warnings':scenario.get('warnings',[]),'simulated':True,'ledger_modified':False}
        if action=='analysis.status':return analysis_status()
        if action=='analysis':
            self.require(state,'accounts')
            if set(args)-{'tool','args'}:raise Fault('INVALID_ARGUMENT','会话数据与上下文由服务端提供')
            try:return run_analysis_tool(args.get('tool','analysis.pipeline'),args.get('args'),state)
            except AnalysisError as exc:raise Fault(exc.code,exc.message) from exc
        if action=='rpc':
            method=args.get('method');params=args.get('args',[])
            if method not in METHODS:raise Fault('TOOL_NOT_REGISTERED','不支持的业务工具')
            if not isinstance(params,list) or len(params)>4:raise Fault('INVALID_ARGUMENT','工具参数必须为数组且不超过四项')
            # Older dedicated transfer API records also appear in the common task UI.
            if method in {'verify','execute','cancel','reconcile'} and params:
                old=next((o for o in state['transfer_ops'] if o['id']==params[0]),None)
                if old:
                    routes={'verify':('transfer.verify',{'operation_id':old['id'],'code':params[1]}),
                            'execute':('transfer.confirm',{'operation_id':old['id'],'confirmed':True,
                                      'assertion_id':old.get('assertion',{}).get('assertion_id'),'outcome':params[1]})} if method in {'verify','execute'} else {}
                    if method=='cancel':return self.dispatch(db,state,'transfer.cancel',{'operation_id':old['id']})
                    if method=='reconcile':return self.dispatch(db,state,'transfer.reconcile',{'operation_id':old['id'],'result':params[1]})
                    return self.dispatch(db,state,*routes[method])
            if method=='authorize' and params and isinstance(params[0],dict) and 'cards' in params[0] and type(params[0]['cards']) is not bool:
                raise Fault('INVALID_ARGUMENT','卡管理权限必须为布尔值')
            if method=='interpret' and params and isinstance(params[0],str):
                text=params[0]
                if self.scanner.scan_input(text).injection_suspected:raise Fault('INJECTION_BLOCKED','不能绕过授权或确认')
                if re.search('什么是|解释一下|怎么理解|了解.*比率',text):
                    return {'route':'knowledge','question':text,'message':'正在查找参考资料；这不是对个人账户的判断。'}
                if re.search('分析现金流|现金流与预算|预算建议|储蓄率|流动性分析|可投金额',text):
                    return {'route':'finance','tool':'analysis.pipeline','message':'基于当前账户资料分析资金安排。'}
                if re.search('整理数据|账户概况',text):
                    return {'route':'finance','tool':'data.organize','message':'正在查询当前账户概况。'}
            if method=='assistant':
                if len(params)!=1 or not isinstance(params[0],str) or not 1<=len(params[0].strip())<=500:raise Fault('INVALID_ARGUMENT','请输入1–500个字符')
                text=params[0]
                if self.scanner.scan_input(text).injection_suspected:raise Fault('INJECTION_BLOCKED','不能绕过授权或确认')
                extra=extensions.answer(self,state,text)
                if extra:return extra
                candidate=parse_transfer(text,context=bool(state.get('assistant_transfer')))
                if candidate is None and re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?\s*(?:元|块|块钱)?',text.strip()):candidate=parse_transfer(text,context=True)
                if candidate is not None:return self.assistant_fill(state,candidate)
                state['assistant_transfer']=None
                state['clarification']=None
                routed=self.dispatch(db,state,'rpc',{'method':'interpret','args':[text]})
                if not routed.get('route') and not routed.get('choices') and re.search('什么|为什么|如何|怎么|解释|吗|？|\\?',text):
                    return {'route':'knowledge','question':text,'message':'正在查找本地资料；不足时不会自动外发问题。'}
                return routed
            if method=='interpret':
                if not params or not isinstance(params[0],str):raise Fault('INVALID_ARGUMENT','意图文本必须为字符串')
                if self.scanner.scan_input(params[0]).injection_suspected:raise Fault('INJECTION_BLOCKED','检测到绕过权限或审批的指令')
                params=[self.scanner.redact_text(params[0])]
            if method in READ:self.require(state,'accounts')
            if method not in {'assistant','authorize','cancel','pause','resume','unlock','interpret','eligibility','total','capacity','monthlySaved','projection','summary','analyze','reviewSubscription','keep','reconcile','settle','settleCard'} and any(o['status']=='unknown' for o in state['transfer_ops']):
                raise Fault('UNKNOWN_OPERATION','未知转账尚未核实，禁止后续写入')
            if method=='propose':
                if any(o['status'] in {'unknown','awaiting_confirmation'} for o in state['transfer_ops']):raise Fault('PENDING_OPERATION','请先处理待执行或未知转账')
                if params and params[0]=='transfer':
                    self.check_transfer_limits(state,params[2])
                    self.require_recipient(state,params[1])
            if method in {'verify','execute'}:
                op=self.pending(state,params[0]);self.check_pending(state,op)
                if op in state['transfer_ops']:raise Fault('INVALID_ARGUMENT','转账请使用转账确认接口')
                if op['type']=='transfer':
                    self.check_transfer_limits(state,op['amount'])
                    self.require_recipient(state,op['target'])
                if method=='execute':self.pending_from_engine_assertion(state,params[0])
            result=self.engine_call(state,method,params)
            if method=='propose':
                result=self.attach(state,self.pending(state,result['id']))
                if params[0]=='transfer':
                    recipient=self.require_recipient(state,params[1])
                    state['assistant_transfer']={'recipient_alias':recipient['name'],'recipientId':params[1],'amount_minor':params[2],'amount_text':str(Decimal(params[2])/100),'currency_text':'元','status':'ready','operation_id':result['id']}
            if method=='verify':
                # Real assertion service is replaceable; this branch is explicitly simulated.
                op=self.pending(state,params[0]);op['assertion_expires_at']=self.clock()+120
                op['assertion_hash']=op['preview_hash']
            if method=='execute':
                # Engine checks verified; integration also checks assertion binding / TTL.
                before=self.pending_from_engine_assertion(state,params[0])
            self.invalidate_transfers(state)
            return result
        if action=='snapshot':
            out=self.engine(state);return {'state':self.public_state(state),'catalog':out['catalog'],'total':out['total'],'capacity':out['capacity']}
        if action=='accounts':
            self.require(state,'accounts');return {'account_id':'ACC-4821','currency':'CNY','available_minor':state['available'],
                'positions_minor':sum(p['amount'] for p in state['positions']),'total_minor':self.engine(state)['total'],'version':state['version']}
        if action=='transactions':
            self.require(state,'transactions');month=args.get('month',datetime.fromtimestamp(state['day']/1000,timezone.utc).strftime('%Y-%m'))
            return {'items':[x for x in state['transactions'] if x['date'].startswith(month)],'summary':self.engine_call(state,'summary',[month])}
        if action=='subscriptions':self.require(state,'subscriptions');return state['subscriptions']
        if action=='recommend':return self.recommendations(state,args)
        if action=='knowledge':
            question=args.get('question','');result=extensions.concept(question) or self.rag.ask(question,args.get('top_k',3))
            result['risk_notice']='团队教育演示资料；未审核为真实银行条款或法规'
            return result
        if action=='transfer.preview':return self.transfer_preview(state,args)
        if action=='transfer.verify':
            op=self.pending(state,args['operation_id']);self.check_pending(state,op);self.require(state,'transfer')
            if op['type']!='transfer':raise Fault('INVALID_ARGUMENT','不是转账操作')
            if args.get('code')!='246810':
                state['failures']+=1
                if state['failures']>=3:state['locked']=True
                e=Fault('AUTH_INVALID','演示验证码错误');e.persist=True;raise e
            assertion=StepUpAssertion('ASSERT-'+uuid4().hex,state['customer_id'],state['session_id'],op['preview_hash'],
                                      stamp(),datetime.fromtimestamp(self.clock()+120,timezone.utc).isoformat())
            op['assertion']={**assertion.__dict__,'expires_epoch':self.clock()+120,'consumed':False}
            return {'assertion_id':assertion.assertion_id,'simulated':True,'expires_at':assertion.expires_at}
        if action=='transfer.confirm':return self.transfer_confirm(state,args)
        if action=='operation':return deepcopy(self.pending(state,args['operation_id']))
        if action=='transfer.reconcile':return self.transfer_reconcile(state,args)
        if action=='transfer.cancel':
            op=self.pending(state,args['operation_id'])
            if op['type']!='transfer':raise Fault('INVALID_ARGUMENT','不是转账操作')
            self.check_pending(state,op);op['status']='cancelled';return deepcopy(op)
        if action=='chat':return self.chat(state,args)
        if action=='events':
            rows=db.execute('SELECT id,at,action,status,detail FROM audit WHERE sid=? ORDER BY id DESC LIMIT 100',(state['session_id'],)).fetchall()
            return [dict(zip(['id','at','action','status','detail'],r)) for r in rows]
        raise Fault('TOOL_NOT_REGISTERED','未注册的接口',404)

    def pending_from_engine_assertion(self,state,op_id):
        # Called after the deterministic engine inside the same DB transaction;
        # failures roll back the entire mutation, including ledger changes.
        op=self.pending(state,op_id)
        if op.get('level')=='red' and (self.clock()>=op.get('assertion_expires_at',0) or op.get('assertion_hash')!=op.get('preview_hash')):
            raise Fault('AUTH_EXPIRED','演示验证过期或绑定不符，请重新验证')
        return op

    def public_state(self,state):
        result=deepcopy(state)
        result.pop('session_id',None)
        result.pop('market_data',None)
        result['market_status']=extensions.market_status(self.market_data)
        if self.market_load_error: result['market_status']['message']=self.market_load_error
        for op in result['operations']+result['transfer_ops']:op.pop('assertion',None)
        # A display projection only: authoritative operation objects are not duplicated.
        for op in result['transfer_ops']:
            view=deepcopy(op)
            view.update(legacy=True,name='转给 '+op['beneficiary_name'],createdAt=op['created_at'],
                        cardId='CARD-DEBIT',dependencies=['名册','余额与累计','明确确认'],
                        snapshot=op.get('snapshot',{'available':None,'goal':state['goal'],'profile':state['profile'],
                                                  'scope':state['consent'],'catalog':'历史快照未保存'}))
            result['operations'].append(view)
        return result

    def transfer_policy(self,state,args):
        self.require(state,'transfer')
        card=next(c for c in state['cards'] if c['id']=='CARD-DEBIT')
        spent=card['spent'] if card['spentDay']==state['day'] else 0
        if card['status']!='active':raise Fault('CARD_BLOCKED','付款卡已限制或挂失')
        if type(args.get('amount_minor')) is int and spent+args['amount_minor']>card['limit']:raise Fault('CARD_LIMIT','超出付款卡当日限额')
        if not state['active'] or state['locked']:raise Fault('EXECUTION_LOCKED','任务暂停或执行锁定')
        if any(o['status']=='unknown' for o in state['operations']+state['transfer_ops']):raise Fault('UNKNOWN_OPERATION','先查询未知操作回执，不能重复执行')
        amount=integer(args.get('amount_minor'),1)
        bank=MockBank();account=bank.find_account('CUST-001',args.get('account_id','ACC-4821'))
        if account['account_id']!='ACC-4821':raise Fault('UNSUPPORTED_ACCOUNT','首版统一账本只支持 ACC-4821 转出')
        account['balance']=account['available']=D(Decimal(state['available'])/100)
        day=datetime.fromtimestamp(state['day']/1000,timezone.utc).date().isoformat()
        used=sum(-x['amount'] for x in state['transactions'] if x.get('category')=='transfer' and x.get('date')==day)
        bank.daily_transfer_total=lambda *a,**kw:D(Decimal(used)/100)
        recipient=self.resolve_recipient(state,args.get('beneficiary_name'),args.get('beneficiary_id'))
        bank.beneficiaries={recipient['beneficiary_id']:recipient}
        _,beneficiary,_=ToolRegistry(bank)._validate_transfer(state['customer_id'],'ACC-4821',recipient['name'],Decimal(amount)/100)
        return amount,beneficiary,day,used

    def check_transfer_limits(self,state,value):
        self.require(state,'transfer');amount=integer(value,1)
        day=datetime.fromtimestamp(state['day']/1000,timezone.utc).date().isoformat()
        used=sum(-x['amount'] for x in state['transactions'] if x.get('category')=='transfer' and x.get('date')==day)
        if amount>int(D(POLICY['single_transfer_limit_cny'])*100) or used+amount>int(D(POLICY['daily_transfer_limit_cny'])*100):
            raise Fault('TRANSFER_LIMIT','超过模拟银行单笔或累计硬限额')

    def transfer_preview(self,state,args):
        amount,beneficiary,day,used=self.transfer_policy(state,args)
        if any(o['status'] in {'unknown','awaiting_confirmation'} for o in state['operations']+state['transfer_ops']):
            raise Fault('PENDING_OPERATION','请先处理已有待确认或未知操作')
        op={'id':'TR-'+uuid4().hex,'type':'transfer','target':beneficiary['beneficiary_id'],'beneficiary_name':beneficiary['name'],
            'amount':amount,'account_id':'ACC-4821','version':state['version'],'status':'awaiting_confirmation',
            'level':'red' if used+amount>100000 else 'yellow','created_at':stamp(),'day':day,
            'snapshot':{'available':state['available'],'goal':deepcopy(state['goal']),'profile':state['profile'],
                        'scope':deepcopy(state['consent']),'catalog':'统一模拟目录'},
            'request':{'amount_minor':amount,'beneficiary_name':beneficiary['name'],
                       'beneficiary_id':beneficiary['beneficiary_id'],'account_id':'ACC-4821'}}
        state['transfer_ops'].append(op);self.attach(state,op)
        return deepcopy(op)

    def transfer_confirm(self,state,args):
        op=self.pending(state,args['operation_id'])
        if op['type']!='transfer':raise Fault('INVALID_ARGUMENT','不是转账操作')
        self.check_pending(state,op)
        amount,beneficiary,day,used=self.transfer_policy(state,op['request'])
        if args.get('confirmed') is not True:raise Fault('APPROVAL_REQUIRED','必须明确确认具体转账')
        if op['level']=='red' or used+amount>100000:
            assertion=op.get('assertion',{})
            if (assertion.get('assertion_id')!=args.get('assertion_id') or assertion.get('consumed',True)
                or self.clock()>=assertion.get('expires_epoch',0) or assertion.get('preview_hash')!=op['preview_hash']
                or assertion.get('user_id')!=state['customer_id'] or assertion.get('session_id')!=state['session_id']):
                raise Fault('AUTH_REQUIRED','需要与本次预览绑定且未过期的演示验证断言')
            assertion['consumed']=True
        outcome=args.get('outcome','success')
        if outcome not in {'success','failed','unknown'}:raise Fault('INVALID_ARGUMENT','无效模拟结果')
        if outcome=='unknown':op['status']='unknown'
        elif outcome=='failed':
            op['status']='failed';state['failures']+=1
            if state['failures']>=3:state['locked']=True
        else:self.apply_transfer(state,op,day,used)
        return deepcopy(op)

    def apply_transfer(self,state,op,day,used):
        state['available']-=op['amount'];state['externalOut']=state.get('externalOut',0)+op['amount'];state['version']+=1
        state['daily_transfers'][day]=state['daily_transfers'].get(day,0)+op['amount']
        card=next(c for c in state['cards'] if c['id']=='CARD-DEBIT')
        card['spent']=(card['spent'] if card['spentDay']==state['day'] else 0)+op['amount'];card['spentDay']=state['day'];op['status']='succeeded';op['receipt_id']='RCPT-'+uuid4().hex
        state['failures']=0
        state['transactions'].append({'id':op['receipt_id'],'date':day,'name':'转账给'+op['beneficiary_name'],'category':'transfer','amount':-op['amount'],'status':'booked','source':'持久化模拟银行回执'})
        for other in state['operations']+state['transfer_ops']:
            if other['status']=='awaiting_confirmation':other['status']='invalidated'
        # The completed operation is no longer awaiting confirmation.
        op['status']='succeeded'
        state['goal']['total']=min(state['goal']['total'],state['available'])
        state['amount']=min(state['amount'],max(0,state['goal']['total']-state['goal']['need']-state['goal']['emergency']))
        self.engine(state) # Ledger invariant must still hold before SQLite commit.

    def transfer_reconcile(self,state,args):
        self.require(state,'accounts');op=self.pending(state,args['operation_id'])
        if op['type']!='transfer' or op['status']!='unknown':raise Fault('INVALID_STATE','没有待查询的未知转账')
        result=args.get('result')
        if result=='success':
            day=op['day'];used=sum(-x['amount'] for x in state['transactions'] if x.get('category')=='transfer' and x.get('date')==day)
            # No writes were allowed while this result was unknown.
            if op['amount']>state['available']:raise Fault('LEDGER_CONFLICT','未知转账核验时余额冲突')
            self.apply_transfer(state,op,day,used)
        elif result=='failed':op['status']='failed'
        elif result!='pending':raise Fault('INVALID_ARGUMENT','无效回执结果')
        return deepcopy(op)

    def recommendations(self,state,args):
        self.require(state,'recommend')
        out=self.engine(state);products=[]
        for p in out['catalog']:
            products.append({'product_id':p['id'],'name':p['name'],'risk_level':p['risk'],'min_investment_cny':p['min']/100,
                'lockup_days':p['term']*30,'redemption_days':1,'category':'cash' if not p['term'] else 'fixed_income',
                'objectives':['liquidity'] if not p['term'] else ['income'],'active':True,'facts_verified':p['redemption']!='unsupported',
                'currency':'CNY','annual_fee_pct':None if p['redemption']=='unsupported' else 0})
        # Calendar days include next-day settlement; engine eligibility remains binding too.
        profile={'user_id':state['customer_id'],'risk_tolerance':1 if state['profile']=='valid' else None,'risk_capacity':1,
                 'budget_cny':min(state['amount'],out['capacity'])/100,'horizon_days':state['goal']['months']*30,'max_redemption_days':1,'objective':args.get('objective','liquidity'),'preferred_categories':['cash']}
        capacity=min(state['amount'],out['capacity'])
        basis={'configured_minor':state['amount'],'engine_capacity_minor':out['capacity'],
               'analysis_headroom_minor':None,'applied_minor':capacity,'source':'engine_capacity',
               'analysis_status':'not_authorized'}
        warnings=[]
        if state['consent']['read']:
            try:
                self.require(state,'accounts')
                # The same organizer view is consumed by ranking and exposed to teammates.
                package=run_analysis_tool('data.organize',{},state)['result']
                view=package['views']['recommendation']
                headroom=view['conditions']['analysis_headroom_minor']
                basis.update(analysis_headroom_minor=headroom,analysis_status='available')
                applied=min(capacity,view['conditions']['budget_minor'])
                profile=dict(view['profile']);profile['budget_cny']=applied/100
                profile['objective']=args.get('objective',profile['objective'])
                basis['applied_minor']=applied
                if applied<capacity:basis['source']='analysis'
                warnings.extend(package['manifest']['warnings'])
            except (AnalysisError,Fault):
                basis['analysis_status']='unavailable'
                warnings.append('分析不可用，采用原有配置与引擎容量；未改动账本')
        result=recommend(profile,products,args.get('top_k',3));result['money_unit']='CNY minor units at external boundary; ranking adapter alone converts to CNY'
        result['budget_basis']=basis
        result['warnings']=list(dict.fromkeys(result.get('warnings',[])+warnings))
        return result

    def assistant_fill(self,state,candidate):
        """Conversation collects form fields; only the form creates an operation."""
        prior=deepcopy(state.get('assistant_transfer') or {})
        c=deepcopy(candidate);act=c['speech_act']
        def answer(message,code='MISSING_SLOT',ready=False):
            return {'route':'transfer-form' if ready else 'transfer-conversation','conclusion':message,
                    'reason_code':code,'transfer':deepcopy(state.get('assistant_transfer')),
                    '_status':'succeeded' if ready else 'needs_input'}
        def retire(status='invalidated'):
            oid=prior.get('operation_id')
            op=next((o for o in state['operations']+state['transfer_ops'] if o['id']==oid),None)
            if op and op['status']=='awaiting_confirmation':
                op['status']=status
                for key in ('assertion','assertion_hash','assertion_expires_at'):op.pop(key,None)
            return op
        if act in {'cancellation','negation'}:
            op=retire('cancelled')
            state['assistant_transfer']=None
            if op and op['status'] in {'unknown','processing','succeeded'}:
                return answer('这笔操作已提交或结果待核实，不能撤回。请查看原回执。','CANCEL_NOT_AVAILABLE')
            return answer('已取消未执行的填写请求，没有因此扣款。','CANCELLED')
        if act in {'question','quoted_example'}:
            return answer('本轮没有新建转账。查询结果请查看任务与记录。','TRANSFER_QUERY')
        if act=='correction':
            if not prior:return answer('请先说明给谁转账及金额。','CONTEXT_REQUIRED')
            op=retire()
            if op and op['status'] in {'unknown','processing','succeeded'}:
                return answer('这笔操作已经提交，不能修改金额，请核对原回执。','CANCEL_NOT_AVAILABLE')
            c['recipient_alias']=prior.get('recipient_alias')
        elif c.get('is_fragment'):
            c['recipient_alias']=c.get('recipient_alias') or prior.get('recipient_alias')
            if c.get('amount_text') is None and prior.get('amount_minor') is not None:
                for key in ('amount_text','amount_minor','currency_text'):c[key]=prior.get(key)
        else:
            retire()  # A fresh request cannot leave a previous confirmation executable.
        issues=set(c.get('issues',[]))
        # A bare amount is only accepted as CNY while answering this explicit amount question.
        assumed=bool(prior.get('recipient_alias') and c.get('is_fragment') and re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?',c.get('amount_text') or '') and 'missing_currency' in issues)
        if assumed:
            c['amount_minor']=int(Decimal(c['amount_text'])*100);c['currency_text']='元';issues.discard('missing_currency')
        saved={k:c.get(k) for k in ('recipient_alias','amount_minor','amount_text','currency_text')}
        saved['status']='needs_input';state['assistant_transfer']=saved
        if act=='unknown' or issues & {'unsupported_expression','multiple_requests'}:
            state['assistant_transfer']=None
            return answer('暂不支持条件、预约、多笔或中文金额，请说明一笔即时人民币转账。','UNSUPPORTED_EXPRESSION')
        if issues & {'amount_invalid','currency_unsupported','ambiguous_amount'}:
            saved['amount_minor']=None
            return answer('请填写大于零、最多两位小数的人民币金额，不使用负数、外币或多个金额。','AMOUNT_INVALID')
        if not saved['recipient_alias']:return answer('请说明收款人姓名；金额信息会保留。')
        try:r=self.resolve_recipient(state,saved['recipient_alias'])
        except Fault as exc:return answer(exc.message,exc.code)
        if not r['whitelisted']:return answer('该演示收款人未准入，请选择其他收款人。','POLICY_DENIED')
        saved['recipientId']=r['beneficiary_id']
        if saved['amount_minor'] is None:
            return answer('请确认人民币单位，例如“800元”。' if 'missing_currency' in issues else f"给{r['name']}转多少钱？可输入800元、800块或800。")
        saved['status']='ready'
        return answer(('按人民币理解。' if assumed else '')+'已根据对话填写收款人和金额，请在转账页面核对；尚未生成确认或扣款。','READY_TO_FILL',True)

    def chat_draft(self,state):
        draft_id=state.get('chat_draft_id')
        return next((o for o in state['transfer_ops'] if o['id']==draft_id),None)

    def retire_chat_draft(self,state,status='invalidated'):
        draft=self.chat_draft(state)
        if draft and draft['status']=='awaiting_confirmation':
            draft['status']=status
            for key in ('assertion','assertion_hash','assertion_expires_at'):
                draft.pop(key,None)
            state['chat_draft_id']=None
            return True
        return False

    def transfer_chat(self,state,candidate):
        """A parsed candidate has no authority; preview uses the normal gate."""
        candidate=deepcopy(candidate)
        act=candidate['speech_act']
        prior=state.get('clarification') or {}
        clear=False

        def response(code,message,missing=None,clear_pending=False,status='needs_input'):
            return {'intent':'transfer','_status':status,'candidate':candidate,
                    'reason_code':code,'missing':missing or [],'clear_pending':clear_pending,
                    'analysis':'依据当前输入、已关联草稿与服务端演示名册核对',
                    'conclusion':message}

        if act=='cancellation':
            draft=self.chat_draft(state)
            state['clarification']=None
            if draft and draft['status'] in {'unknown','submitting','processing','succeeded'}:
                return response('CANCEL_NOT_AVAILABLE','这笔操作已提交或结果待核对，不能通过对话撤回。请先查看原操作回执。')
            cancelled=self.retire_chat_draft(state,'cancelled')
            return response('CANCELLED' if cancelled or prior else 'NO_ACTIVE_DRAFT',
                            '已取消本对话的待确认转账或待补充请求。' if cancelled or prior else '本对话没有待确认转账，请到操作记录核对其他转账。',
                            clear_pending=True,status='cancelled' if cancelled or prior else 'succeeded')
        if act=='negation':
            retired=self.retire_chat_draft(state)
            state['clarification']=None
            message=('已停止本对话的待确认草稿，本轮没有新建转账。' if retired else
                     '本轮没有新建转账。已提交或结果待核对的操作不会因此撤回，请查看原操作回执。')
            draft=self.chat_draft(state)
            keep_unknown=bool(draft and draft['status']=='unknown')
            return response('NEGATED_REQUEST',message,clear_pending=not keep_unknown,status='succeeded')
        if act in {'question','quoted_example'}:
            state['clarification']=None
            return response('TRANSFER_QUERY' if act=='question' else 'QUOTED_EXAMPLE',
                            '这是转账相关查询或示例，本轮没有新建转账。查询是否到账请查看转账记录并核对原操作回执。',status='succeeded')
        if act=='correction':
            draft=self.chat_draft(state)
            if not draft or draft['status']!='awaiting_confirmation':
                return response('CONTEXT_REQUIRED','没有本对话关联的待确认转账；结果未知时请先核对原操作回执。',
                                clear_pending=not (draft and draft['status']=='unknown'))
            # Any explicit correction revokes the old confirmation, even if the
            # replacement later needs clarification or fails policy validation.
            candidate['recipient_alias']=candidate.get('recipient_alias') or draft['beneficiary_name']
            self.retire_chat_draft(state)
            clear=True
            state['clarification']=None
        elif candidate.get('is_fragment'):
            if not prior:
                return response('CONTEXT_REQUIRED','请先说明要给谁转账及金额。')
            if candidate.get('recipient_alias') is None:
                candidate['recipient_alias']=prior.get('recipient_alias')
            if candidate.get('amount_text') is None and prior.get('amount_minor') is not None:
                for key in ('amount_text','amount_minor','currency_text'):
                    candidate[key]=prior.get(key)

        issues=set(candidate.get('issues',[]))
        if act=='unknown' or issues & {'unsupported_expression','multiple_requests'}:
            self.retire_chat_draft(state)
            state['clarification']=None
            draft=self.chat_draft(state)
            return response('MULTIPLE_REQUESTS' if 'multiple_requests' in issues else 'UNSUPPORTED_EXPRESSION',
                            '本版本暂不支持这类条件、预约、多笔或复杂表达，请分别明确一笔即时转账，或使用对应表单。',
                            clear_pending=not (draft and draft['status']=='unknown'))

        # Retain only safely recognized slots for a subsequent explicit fragment.
        saved={'recipient_alias':candidate.get('recipient_alias'),
               'amount_minor':candidate.get('amount_minor'),
               'amount_text':candidate.get('amount_text'),
               'currency_text':candidate.get('currency_text')}
        state['clarification']=saved
        if 'amount_invalid' in issues:
            saved['amount_minor']=None
            return response('AMOUNT_INVALID','金额格式无效：请使用大于零、最多两位小数的明确金额，不能使用负数、科学计数或不支持的分隔格式。',['amount_minor'],clear)
        if 'currency_unsupported' in issues:
            saved['amount_minor']=None
            return response('CURRENCY_UNSUPPORTED','当前演示只支持人民币，请明确人民币金额；不会把外币直接换成人民币。',['currency_text'],clear)
        if 'ambiguous_amount' in issues:
            saved['amount_minor']=None
            return response('AMBIGUOUS_INPUT','识别到多个金额，请明确本笔使用哪一个金额。',['amount_minor'],clear)

        missing=[]
        if not candidate.get('recipient_alias'):missing.append('beneficiary_name')
        if candidate.get('amount_minor') is None:missing.append('amount_minor')
        if 'missing_currency' in issues and candidate.get('currency_text') is None:
            return response('CURRENCY_REQUIRED','请确认金额单位，例如“800元”。',['currency_text'],clear)
        if missing:
            message=('请说明收款人及人民币金额，例如：给小王转账800元。' if len(missing)==2 else
                     f"要给{candidate['recipient_alias']}转多少元？" if missing==['amount_minor'] else
                     '金额已保留，请说明收款人姓名。')
            return response('MISSING_SLOT',message,missing,clear)
        try:
            recipient=self.resolve_recipient(state,candidate['recipient_alias'])
        except Fault as exc:
            return response(exc.code,exc.message,['beneficiary_name'],clear)
        try:
            preview=self.transfer_preview(state,{'beneficiary_name':recipient['name'],
                'beneficiary_id':recipient['beneficiary_id'],'amount_minor':candidate['amount_minor']})
        except (Fault,ToolError) as exc:
            if clear:exc.persist=True
            raise
        state['clarification']=None
        state['chat_draft_id']=preview['id']
        return {'intent':'transfer','_status':'awaiting_confirmation','candidate':candidate,
                'reason_code':'READY_FOR_CONFIRMATION','clear_pending':clear,
                'analysis':'已解析一笔即时转账，并通过收款名册、权限、金额、卡状态和限额校验',
                'plan':[{'id':'read','depends_on':[]},{'id':'preview','depends_on':['read']},
                        {'id':'confirm','depends_on':['preview']},{'id':'receipt','depends_on':['confirm']}],
                'preview':preview,'conclusion':'请核对收款人和金额后明确确认；本轮仅生成模拟预览。'}

    def chat(self,state,args):
        text=args.get('message','')
        if not isinstance(text,str) or not 1<=len(text.strip())<=2000:raise Fault('INVALID_ARGUMENT','请输入 1–2000 个字符')
        if self.scanner.scan_input(text).injection_suspected:raise Fault('INJECTION_BLOCKED','检测到绕过权限或审批的指令')
        extra=extensions.answer(self,state,text)
        if extra:return extra
        candidate=parse_transfer(text,context=bool(state.get('clarification')))
        if candidate is not None:return self.transfer_chat(state,candidate)
        if re.search('他人|别人|朋友的|家人的',text):raise Fault('OWNERSHIP_DENIED','只能处理当前演示客户的账户')
        # An unrelated new task ends incomplete slot filling instead of being
        # swallowed by the old transfer branch. Existing confirmed drafts stay
        # governed by their own operation state.
        state['clarification']=None
        tasks=[]
        if re.search('余额|多少钱',text):tasks.append(('accounts',{}))
        if re.search('账单|消费|支出|现金流|储蓄率',text):tasks.append(('transactions',{'month':args.get('month',datetime.fromtimestamp(state['day']/1000,timezone.utc).strftime('%Y-%m'))}))
        if re.search('订阅|扣费',text):tasks.append(('subscriptions',{}))
        if re.search('理财|推荐|投资',text):tasks.append(('recommend',{}))
        analysis_tool = ('data.organize' if re.search('数据整理|整理数据|卡片视图',text) else
                         'budget.advice' if re.search('预算建议|可投金额|应急金',text) else
                         'analysis.pipeline' if re.search('分析|现金流|储蓄率|流动性|异常',text) else None)
        if analysis_tool:
            tasks=[task for task in tasks if task[0]!='transactions']
            tasks.append(('analysis',{'tool':analysis_tool,'args':{}}))
        if not tasks:tasks=[('knowledge',{'question':text})]
        results=[];plan=[]
        for i,(tool,params) in enumerate(tasks):
            plan.append({'id':str(i+1),'tool':tool,'depends_on':[str(i)] if i else []})
            if tool=='accounts':self.require(state,'accounts');data={'available_minor':state['available'],'currency':'CNY'}
            elif tool=='transactions':self.require(state,'transactions');data=self.engine_call(state,'summary',[params['month']])
            elif tool=='subscriptions':self.require(state,'subscriptions');data=deepcopy(state['subscriptions'])
            elif tool=='recommend':data=self.recommendations(state,{})
            elif tool=='analysis':
                self.require(state,'accounts')
                try:data=run_analysis_tool(params['tool'],params['args'],state)
                except AnalysisError as exc:raise Fault(exc.code,exc.message) from exc
            else:data=self.rag.ask(text,3)
            results.append({'tool':tool,'result':data})
        log={'at':stamp(),'message':self.scanner.redact_text(text),'plan':plan,'status':'succeeded'}
        state['task_log'].append(log)
        return {'intent':'multi_task' if len(tasks)>1 else tasks[0][0],'analysis':'按已授权业务工具读取数据；知识问题仅返回可追溯原文依据',
                'plan':plan,'results':results,'conclusion':'本轮查询完成；未自动执行金融变更'}
