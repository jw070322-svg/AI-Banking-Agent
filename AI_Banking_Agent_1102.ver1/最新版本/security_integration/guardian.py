"""Per-request Guardian ports backed by the caller's existing SQLite transaction.

No demo bank or second balance store is constructed. A browser execute request
is the explicit user approval; its pending operation is rechecked before
bridging it to Guardian's one-use confirmation. Local configuration forms use
an exact request/version binding, not a financial approval.
"""
from copy import deepcopy
from datetime import datetime,timezone
from types import SimpleNamespace
from uuid import uuid4
import hmac
from first_agent.service import Fault,POLICY_VERSION
from .privacy import session_tag
from first_agent.vendor.eva.security.hardening import HardenedToolGateway,LockedConfirmationService
from first_agent.vendor.eva.security.models import Principal,SecurityDecision
from first_agent.vendor.eva.security.injection import PromptInjectionGuard,OutputGuard
from first_agent.vendor.eva.security.compatibility import CompatibleScanner
from first_agent.vendor.eva.security.adapters import RiskAuthorizationRegistry,WebApprovalEvidenceBridge,ExistingRiskEngineAdapter,ExistingComplianceGuardAdapter
from first_agent.vendor.eva.security.verification import run_verification,issue_ticket
from first_agent.vendor.eva.tool_calling.models import ToolCallResult
from first_agent.vendor.eva.tool_calling.adapters import RiskEvaluationRequest,ComplianceEvaluationRequest

READ_METHODS={'summary','total','capacity','monthlySaved','projection','liquid','eligibility','interpret'}
LOCAL_METHODS={'authorize','configure','select','setProfile','budget','configureSimulation','advance','pause','resume','unlock','keep','reviewSubscription','analyze'}
READ_ACTIONS={'knowledge','external.status','external.probe','external.search','local_life.links','snapshot','accounts','transactions','subscriptions','recommend','events','analysis.status','operation','recipients','audit.export','calendar.list','market.status','market.context','market.recommend','scenario.generate'}

class SqlAudit:
    def __init__(self,db,sid):self.db,self.sid=db,session_tag(sid)
    def try_log(self,event_type,**kwargs):
        return self.log(event_type,**kwargs)
    def log(self,event_type,**kwargs):
        event_id=uuid4().hex
        # Server-defined enum and correlation only: no args, secrets or prompts.
        decision=kwargs.get('decision')
        self.db.execute('INSERT INTO guardian_events VALUES(?,?,?,?,?)',(event_id,self.sid,event_type,
            str(getattr(decision,'decision','unknown')),datetime.now(timezone.utc).isoformat()))
        return SimpleNamespace(event_id=event_id)

class SessionPort:
    def __init__(self,principal,token):self.principal,self.token=principal,token
    def validate_session(self,token,require_csrf=None):
        valid=isinstance(token,str) and hmac.compare_digest(token,self.token)
        return SimpleNamespace(ok=valid,principal=self.principal if valid else None,
            decision=SecurityDecision.allow('authentication','LOCAL_DEMO_SESSION') if valid else SecurityDecision.block('authentication','SESSION_INVALID'))

class Resolver:
    def owned_account_ids(self,user_id):return {'ACC-4821'}
    def all_account_ids(self):return {'ACC-4821'}

class LedgerAuthorizationPort:
    """Resolve session ownership and current permissions from the one web ledger."""
    def __init__(self,port):
        self.port=port
        self.resolver=Resolver()
    def authorize(self,principal,trace_id):
        state=self.port.state
        if principal.session_id!=state['session_id'] or principal.user_id!=state['customer_id']:
            return SecurityDecision.block('authorization','SESSION_MISMATCH',trace_id=trace_id)
        self.port.check_business_scope()
        return SecurityDecision.allow('authorization','WEB_LEDGER_SCOPE',trace_id=trace_id)

class WebGuardian(HardenedToolGateway):
    def _authorize_tool(self,principal,tool_name,args,trace_id,phase):
        port=self.registry._registry
        decision=self.authorization.authorize(principal,trace_id)
        if not decision.allowed:return decision,{},None
        return decision,{}, {
            'action':'web.'+port.label,'resource_id':port.operation['id'] if port.operation else principal.session_id,
            'parameters':{'request':args,'ledger_version':port.state['version'],
                'operation_hash':port.operation.get('preview_hash') if port.operation else None}}

class RegistryPort:
    def __init__(self,service,db,state,action,args,dispatch,ticket,replay_response=None):
        self.service,self.db,self.state,self.action,self.args,self.dispatch=service,db,state,action,args,dispatch
        self.method=args.get('method') if action=='rpc' else None
        self.params=args.get('args',[]) if action=='rpc' else []
        self.label=action+'.'+self.method if isinstance(self.method,str) else action
        self.exception=None;self.operation=None;self.safety_reached=False
        self.replay_response=replay_response
        if replay_response is not None:self.label+='.cache_read'
        self.registry=RiskAuthorizationRegistry(expected_policy_version=POLICY_VERSION,clock=lambda:datetime.fromtimestamp(service.clock(),timezone.utc))
        self.compliance=ExistingComplianceGuardAdapter(verified=True,ticket=ticket)
        self.risk=ExistingRiskEngineAdapter(self.registry,verified=True,ticket=ticket)
        self.execution=replay_response is None and (action=='transfer.confirm' or (action=='rpc' and self.method=='execute'))
        if self.execution:
            opid=args.get('operation_id') if action=='transfer.confirm' else self.params[0] if self.params else None
            self.operation=service.pending(state,opid)
            service.check_pending(state,self.operation)
            if action=='transfer.confirm' and args.get('confirmed') is not True:raise Fault('APPROVAL_REQUIRED','请确认本次具体操作')
            if self.operation['type']=='transfer':service.check_transfer_limits(state,self.operation['amount'])
            # Keep the original assertion/hash/TTL check. Never trust a posted verified flag.
            if self.operation.get('level')=='red' or self.operation.get('type') in {'purchase','redeem','card_loss','card_limit','card_restrict','card_unlock','card_apply'}:
                self.check_step_up()
        self.mutating=replay_response is None and (self.execution or (action=='rpc' and self.method not in READ_METHODS) or action not in READ_ACTIONS and action!='rpc')
        self.definition=SimpleNamespace(name='web_call',version='1101.1',mutating=self.mutating,
            risk_tier='R4' if self.operation and self.operation.get('level')=='red' else 'R3',simulated=True)

    def check_step_up(self):
        op=self.operation
        self.service.check_pending(self.state,op)
        if op in self.state['transfer_ops']:
            a=op.get('assertion') or {}
            if (a.get('assertion_id')!=self.args.get('assertion_id') or a.get('consumed',True)
                or self.service.clock()>=a.get('expires_epoch',0) or a.get('preview_hash')!=op['preview_hash']
                or a.get('user_id')!=self.state['customer_id'] or a.get('session_id')!=self.state['session_id']):
                raise Fault('AUTH_REQUIRED','需要本次操作有效的模拟验证',403)
        else:
            self.service.pending_from_engine_assertion(self.state,op['id'])
            if not op.get('verified'):raise Fault('AUTH_REQUIRED','请先完成本次模拟验证',403)
        return True

    def check_business_scope(self):
        if self.replay_response is not None:
            from first_agent.replay_access import check_replay_access
            check_replay_access(self.service,self.state,self.action,self.args,self.replay_response)
            return
        s=self.state
        if self.execution:
            kind=self.operation['type']
            if kind in {'transfer','purchase','redeem'}:self.service.require(s,'transfer')
            required='cards' if kind.startswith('card') else 'subscriptions' if kind=='subscription' else None
            if required and not s['consent'].get(required):raise Fault('SCOPE_DENIED','缺少对应演示权限',403)
        # Other reads/configuration retain their existing server rules in dispatch.
        if self.action in {'accounts','transactions','subscriptions'}:self.service.require(s,self.action)
        if self.action in {'knowledge','external.status','external.probe','external.search','local_life.links'}:self.service.require(s,'knowledge')

    def get_definition(self,name):
        if name!='web_call':raise ValueError('unknown tool')
        return self.definition
    def normalize(self,name,args):
        self.get_definition(name)
        if args!=self.args:raise ValueError('request changed')
        return deepcopy(args)

    def execute(self,name,args,context):
        self.safety_reached=True
        try:
            if not self.compliance.is_verified or not self.risk.is_verified:raise Fault('GUARDIAN_UNVERIFIED','安全模块验证已失效',503)
            request=dict(request_id=uuid4().hex,trace_id=context.trace_id,user_id=context.user_id,
                         session_id=context.session_id,tool_name=name,tool_version='1101.1',arguments=args,request_text='')
            verdict=self.compliance.evaluate(ComplianceEvaluationRequest(**request))
            if not verdict.allowed:raise Fault('COMPLIANCE_DENIED','本次操作未通过合规检查',403)
            if self.execution:
                def verify_binding():
                    self.service.check_pending(self.state,self.operation);self.check_business_scope();return True
                if self.operation['type']=='transfer':
                    WebApprovalEvidenceBridge(self.registry).record_from_web_state(self.state,self.operation['id'],
                        tool_name=name,tool_version='1101.1',arguments=args,verify_web_binding=verify_binding)
                else:
                    WebApprovalEvidenceBridge(self.registry).record_from_web_operation(user_id=context.user_id,session_id=context.session_id,
                        tool_name=name,tool_version='1101.1',arguments=args,operation_id=self.operation['id'],
                        preview_hash=self.operation['preview_hash'],expires_at=self.operation['expires_at'],
                        verify_web_binding=verify_binding,risk_level=self.definition.risk_tier)
                risk=self.risk.evaluate(RiskEvaluationRequest(**request,mutating=True,risk_tier=self.definition.risk_tier,
                    permissions=tuple(context.permissions),auth_level=context.auth_level,confirmation_id=context.confirmation_id))
                if not risk.allowed:raise Fault('RISK_DENIED','本次操作缺少有效风险授权',403)
            result=self.dispatch(self.db,self.state,self.action,args)
            def normalize_policy(value):
                if isinstance(value,dict):
                    return {k: ['本次采用基础确认' if x=='无需强验证' else normalize_policy(x) for x in v]
                        if k=='dependencies' and isinstance(v,list) else normalize_policy(v) for k,v in value.items()}
                if isinstance(value,list):return [normalize_policy(x) for x in value]
                return value
            result=normalize_policy(result)
            self.db.execute('INSERT INTO guardian_dispatch VALUES(?,?,?,?,?)',(uuid4().hex,session_tag(context.session_id),self.label,
                context.trace_id,'returned'))
            return ToolCallResult(tool=name,version='1101.1',call_id=uuid4().hex,ok=True,
                status='unknown' if isinstance(result,dict) and result.get('_status',result.get('status'))=='unknown' else 'success',
                data={'result':result},meta={'simulated':True})
        except Exception as exc:
            self.exception=exc
            raise

class GuardianIntegration:
    def __init__(self,service):
        self.service=service
        report=run_verification();self.ticket=issue_ticket(report)
        self.report=report
        with service.transaction() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS guardian_events(id TEXT PRIMARY KEY,sid TEXT,event TEXT,decision TEXT,at TEXT); CREATE TABLE IF NOT EXISTS guardian_dispatch(id TEXT PRIMARY KEY,sid TEXT,action TEXT,trace TEXT,phase TEXT);')
            for table in ('guardian_events','guardian_dispatch'):
                for (sid,) in db.execute('SELECT DISTINCT sid FROM '+table).fetchall():
                    if not sid.startswith('session-sha256:'):
                        db.execute('UPDATE '+table+' SET sid=? WHERE sid=?',(session_tag(sid),sid))

    def execute(self,db,state,action,args,dispatch,replay_response=None):
        self.service.web_security.check(state,action,args)
        port=RegistryPort(self.service,db,state,action,args,dispatch,self.ticket,replay_response=replay_response)
        # Guardian's demo contract calls a validated cookie session 'strong'.
        # This is a LOCAL MOCK level, not proof of real customer identity.
        permissions={'knowledge:read','products:read','local:configuration'}
        if state['consent'].get('read'):permissions.update({'account:read','transactions:read','subscriptions:read'})
        if state['consent'].get('trade'):permissions.update({'transfer:write','transaction:initiate','transaction:execute'})
        if state['consent'].get('cards'):permissions.update({'card:read','card:write'})
        if state['consent'].get('subscriptions'):permissions.add('subscriptions:write')
        principal=Principal(state['customer_id'],('customer',),frozenset(permissions),
            auth_level='strong',session_id=state['session_id'],permission_version=state['version'])
        guard=PromptInjectionGuard(CompatibleScanner());audit=SqlAudit(db,state['session_id'])
        # The original web assertion is the local simulated verifier. Bound to this request only.
        class StepUp:
            def verify(inner,**kw):
                if not port.operation or kw.get('assertion_id')!=port.operation['id']:return False
                try:return port.check_step_up()
                except Exception:return False
        confirmation=LockedConfirmationService(audit=audit,step_up_verifier=StepUp(),
            clock=lambda:datetime.fromtimestamp(self.service.clock(),timezone.utc))
        gateway=WebGuardian(port,SessionPort(principal,state['session_id']),LedgerAuthorizationPort(port),injection_guard=guard,
            confirmation=confirmation,output_guard=OutputGuard(guard,resolver=Resolver()),audit=audit)
        confirmation_id=None
        if port.mutating:
            ready=gateway.prepare_confirmation(state['session_id'],'web_call',args)
            if not ready.ok:raise Fault('GUARDIAN_DENIED','安全确认准备失败，请核对授权与操作状态',403)
            approved=gateway.confirm(state['session_id'],ready.challenge.confirmation_id,
                presented_details=ready.challenge.details,step_up_assertion_id=port.operation['id'] if port.operation else None)
            if not approved.ok:raise Fault('GUARDIAN_DENIED','安全验证未通过',403)
            confirmation_id=ready.challenge.confirmation_id
        outcome=gateway.execute(state['session_id'],'web_call',args,confirmation_id=confirmation_id)
        if port.exception:raise port.exception
        if not outcome.ok or outcome.safe_data is None:
            raise Fault('GUARDIAN_DENIED','安全模块未允许本次操作；请核对授权或原回执',403)
        return outcome.safe_data['result']
