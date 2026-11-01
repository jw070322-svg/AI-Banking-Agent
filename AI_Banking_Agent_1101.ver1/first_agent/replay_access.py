"""Current authorization for reading a session's historical idempotent response.
Never execute a business action to authorize a replay.
"""
from .service import Fault,READ,METHODS,POLICY_VERSION

PUBLIC={'scenario.generate','analysis.status','market.status','market.context','market.recommend','recipients','page.open','calendar.list','calendar.save','calendar.reserve','calendar.release','calendar.google.sync','profile.update'}
PUBLIC_RPC={'authorize','configure','select','setProfile','budget','configureSimulation','advance','pause','resume','unlock','interpret','eligibility','total','capacity','monthlySaved','projection','liquid'}
OP_METHODS={'execute','verify','cancel','reconcile','settle','settleCard'}

def check_replay_access(service,state,action,args,response):
    if not isinstance(args,dict):raise Fault('INVALID_ARGUMENT','请求参数格式不正确')
    if hasattr(service,'web_security'):service.web_security.check(state,action,args)
    if state.get('consentExpiresAt') and service.clock()*1000>=state['consentExpiresAt']:
        raise Fault('SCOPE_EXPIRED','演示授权已过期',403)
    method=args.get('method') if action=='rpc' else None
    params=args.get('args',[]) if action=='rpc' else []
    if action=='rpc' and (not isinstance(method,str) or method not in METHODS or not isinstance(params,list)):
        raise Fault('INVALID_ARGUMENT','缓存请求方法或参数无效')
    # Explicit account/card references still have to resolve in the current session.
    def references(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='account_id' and item!='ACC-4821':raise Fault('RESOURCE_DENIED','账户不在当前范围内',403)
                if key in {'cardId','card_id'} and item is not None and item not in {c['id'] for c in state['cards']}:
                    raise Fault('RESOURCE_DENIED','卡片不在当前会话范围内',403)
                references(item)
        elif isinstance(value,list):
            for item in value:references(item)
    references(args)
    data=response.get('data') if isinstance(response.get('data'),dict) else {}
    chat_preview=action=='chat' and isinstance(data.get('preview'),dict)
    opid=data['preview'].get('id') if chat_preview else args.get('operation_id')
    if action=='rpc' and method in OP_METHODS and params:opid=params[0]
    if (action=='transfer.preview' or action=='rpc' and method=='propose') and isinstance(response.get('data'),dict):
        opid=response['data'].get('id')
    op=service.pending(state,opid) if opid is not None else None
    if op:
        kind=op['type']
        scope='cards' if kind.startswith('card') else 'subscriptions' if kind=='subscription' else 'trade'
        if op['status']=='awaiting_confirmation':
            if not state['consent'].get(scope):raise Fault('SCOPE_DENIED','缺少对应演示权限',403)
            if service.clock()>=op.get('expires_at',0):raise Fault('PREVIEW_EXPIRED','预览已过期，请重新核对',403)
            if op.get('version')!=state['version'] or op.get('preview_hash')!=service.bound_hash(state,op) or op.get('policy_version')!=POLICY_VERSION:
                raise Fault('PREVIEW_STALE','原确认已失效，请重新核对',403)
            if action=='transfer.verify':
                assertion=op.get('assertion') or {}
                if assertion.get('consumed',True) or service.clock()>=assertion.get('expires_epoch',0):
                    raise Fault('AUTH_EXPIRED','模拟验证已失效',403)
            if method=='verify' and op.get('level')=='red':service.pending_from_engine_assertion(state,op['id'])
        else:
            # Completed/failed/unknown receipts are reads, not another execution.
            if not state['consent'].get('read') and not state['consent'].get(scope):
                raise Fault('SCOPE_DENIED','缺少查看该回执的演示权限',403)
            if chat_preview or action=='transfer.preview' or method in {'propose','verify'} or action=='transfer.verify':
                raise Fault('PREVIEW_STALE','原方案或验证已处理，请查看任务回执',403)
        return
    if action=='recommend':
        service.require(state,'recommend');return
    if action=='chat' or action=='rpc' and method=='assistant':
        service.require(state,'accounts');return
    if action=='rpc' and method in READ or action in {'snapshot','accounts','transactions','subscriptions','analysis','events','audit.export','operation'}:
        service.require(state,'accounts')
        return
    if action=='rpc' and method in PUBLIC_RPC or action in PUBLIC:return
    # Unknown cached action must not acquire a new exemption merely by caching.
    if response.get('error') and response.get('data') is None:return
    raise Fault('REPLAY_SCOPE_UNKNOWN','无法核对该缓存的访问权限，请使用当前页面查询',403)
