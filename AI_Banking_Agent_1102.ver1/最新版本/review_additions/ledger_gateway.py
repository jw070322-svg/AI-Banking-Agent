"""Local ledger gateway: no second bank, no second confirmation store.

The legacy dispatcher remains the adapter for the existing business engine.
The standalone 13-tool gateway is not silently substituted: its catalogue and
confirmation objects differ from the web app. This adapter preserves the web
app's transaction-bound confirmations and common SQLite transaction.
"""
from uuid import uuid4
from first_agent.service import Fault, METHODS

class LedgerGateway:
    def __init__(self, service, actions):
        self.service=service
        self.actions=frozenset(actions)
        with service.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS review_gateway_calls(id TEXT PRIMARY KEY,sid TEXT NOT NULL,action TEXT NOT NULL,phase TEXT NOT NULL)')

    def execute(self, db, state, action, args, dispatch):
        if not isinstance(action,str) or action not in self.actions:
            raise Fault('TOOL_NOT_ALLOWED','该操作尚未开放',403)
        self.service.web_security.check(state,action,args)
        if action=='rpc' and args.get('method') not in METHODS:
            raise Fault('TOOL_NOT_ALLOWED','该操作尚未开放',403)
        # Resolve identity from the state already loaded by the server, not args.
        sid=state['session_id']
        if not db.execute('SELECT 1 FROM sessions WHERE sid=?',(sid,)).fetchone():
            raise Fault('SESSION_REQUIRED','会话已失效，请刷新页面',401)
        op_id=None
        if action.startswith('transfer.') and action not in {'transfer.preview'}:
            op_id=args.get('operation_id')
        if action=='rpc' and args.get('method') in {'verify','execute','cancel','reconcile','settle','settleCard'}:
            values=args.get('args')
            if isinstance(values,list) and values:op_id=values[0]
        if op_id is not None and not any(o['id']==op_id for o in state['operations']+state['transfer_ops']):
            raise Fault('NOT_FOUND','当前会话中没有该操作',404)
        identity=str(uuid4())
        label=action+'.'+args['method'] if action=='rpc' else action
        db.execute('INSERT INTO review_gateway_calls VALUES(?,?,?,?)',(identity,sid,label,'admitted'))
        try:
            result=dispatch(db,state,action,args)
        except Exception:
            db.execute('UPDATE review_gateway_calls SET phase=? WHERE id=?',('rejected_or_interrupted',identity))
            raise
        # Returned is deliberately not synonymous with succeeded/settled.
        db.execute('UPDATE review_gateway_calls SET phase=? WHERE id=?',('returned',identity))
        return result
