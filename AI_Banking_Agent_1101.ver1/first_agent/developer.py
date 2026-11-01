"""Local demo test controls. Session-bound tokens are checked server-side."""
from __future__ import annotations
from copy import deepcopy
from contextlib import closing
import hashlib, json, os, secrets

def setup(service):
    with service.transaction() as db:
        db.executescript('CREATE TABLE IF NOT EXISTS developer_tokens(sid TEXT PRIMARY KEY,token_hash TEXT,expires REAL); CREATE TABLE IF NOT EXISTS developer_backups(sid TEXT PRIMARY KEY,state TEXT NOT NULL);')

def validate(service, sid, token):
    from .service import Fault
    if not isinstance(token,str) or not token:raise Fault('DEVELOPER_REQUIRED','请先解锁开发者工具',403)
    with closing(service.connect()) as db:
        row=db.execute('SELECT token_hash,expires FROM developer_tokens WHERE sid=?',(sid,)).fetchone()
    if not row or row[1]<=service.clock() or not secrets.compare_digest(row[0],hashlib.sha256(token.encode()).hexdigest()):
        raise Fault('DEVELOPER_REQUIRED','开发者会话已失效，请重新输入测试密码',403)

def call(service,sid,action,args,token):
    from .service import Fault, canonical
    if action=='login':
        code=args.get('code','')
        if not isinstance(code,str) or not secrets.compare_digest(code,os.environ.get('BANK_DEV_PASSWORD','bnbu')):raise Fault('DEVELOPER_DENIED','测试密码不正确',403)
        value=secrets.token_urlsafe(32)
        with service.transaction() as db:
            service.load(db,sid)
            db.execute('INSERT OR REPLACE INTO developer_tokens VALUES(?,?,?)',(sid,hashlib.sha256(value.encode()).hexdigest(),service.clock()+900))
            backup=bool(db.execute('SELECT 1 FROM developer_backups WHERE sid=?',(sid,)).fetchone())
        return service.envelope({'token':value,'has_backup':backup})
    validate(service,sid,token)
    with service.transaction() as db:
        old=service.load(db,sid)
        if action=='logout':db.execute('DELETE FROM developer_tokens WHERE sid=?',(sid,));return service.envelope({'closed':True})
        if action=='reset':
            if args.get('confirmation')!='重置演示':raise Fault('CONFIRMATION_REQUIRED','未确认重置',400)
            db.execute('INSERT OR REPLACE INTO developer_backups VALUES(?,?)',(sid,canonical(old)))
            fresh=service.engine()['state'];fresh.update(customer_id=old['customer_id'],session_id=sid,transfer_ops=[],daily_transfers={},task_log=[],clarification=None,chat_draft_id=None,assistant_transfer=None)
        elif action=='restore':
            if args.get('confirmation')!='恢复备份':raise Fault('CONFIRMATION_REQUIRED','未确认恢复',400)
            row=db.execute('SELECT state FROM developer_backups WHERE sid=?',(sid,)).fetchone()
            if not row:raise Fault('NOT_FOUND','没有重置前备份',404)
            fresh=json.loads(row[0]);fresh['session_id']=sid
            for op in fresh['operations']+fresh['transfer_ops']:
                if op['status']=='awaiting_confirmation':op['status']='invalidated'
                op['verified']=False;op.pop('assertion',None)
        else:raise Fault('NOT_FOUND','开发者操作不存在',404)
        fresh['version']=max(old['version'],fresh['version'])+1
        db.execute('UPDATE sessions SET state=? WHERE sid=?',(canonical(fresh),sid))
        db.execute('DELETE FROM requests WHERE sid=?',(sid,))
        service.audit(db,sid,'developer.'+action,'succeeded',{'backup_retained':True})
        return service.envelope({'completed':True,'has_backup':True})
