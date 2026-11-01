"""Tamper-evident local audit chain, not external immutable/WORM storage.
Appends share the ledger transaction. Existing history is an explicit baseline.
"""
import hashlib,json
from first_agent.service import Fault

GENESIS='0'*64

def digest(payload):
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class AuditChain:
    def __init__(self, service):
        self.service=service
        with service.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS review_audit_chain(seq INTEGER PRIMARY KEY, audit_id INTEGER UNIQUE, previous TEXT NOT NULL, digest TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS review_audit_baseline(singleton INTEGER PRIMARY KEY CHECK(singleton=1), last_id INTEGER NOT NULL, digest TEXT NOT NULL)')
            if not db.execute('SELECT 1 FROM review_audit_baseline').fetchone():
                rows=db.execute('SELECT id,sid,at,action,status,detail FROM audit ORDER BY id').fetchall()
                db.execute('INSERT INTO review_audit_baseline VALUES(1,?,?)',(rows[-1][0] if rows else 0,digest(rows)))

    def verify(self, db):
        last, baseline=db.execute('SELECT last_id,digest FROM review_audit_baseline').fetchone()
        if digest(db.execute('SELECT id,sid,at,action,status,detail FROM audit WHERE id<=? ORDER BY id',(last,)).fetchall())!=baseline:
            raise Fault('AUDIT_INTEGRITY','历史记录校验失败，已停止新的操作，请联系项目维护者',503)
        rows=db.execute('SELECT id,sid,at,action,status,detail FROM audit WHERE id>? ORDER BY id',(last,)).fetchall()
        links=db.execute('SELECT seq,audit_id,previous,digest FROM review_audit_chain ORDER BY seq').fetchall()
        if len(rows)!=len(links):raise Fault('AUDIT_INTEGRITY','审计记录不完整，已停止新的操作',503)
        prev=baseline
        for n,(row,link) in enumerate(zip(rows,links),1):
            value=digest({'seq':n,'previous':prev,'row':row})
            if link!=(n,row[0],prev,value):raise Fault('AUDIT_INTEGRITY','审计记录校验失败，已停止新的操作',503)
            prev=value
        return {'entries':len(rows),'head':prev,'baseline_last_id':last,'limit':'本地可检测修改；管理员重写整个链或删去完整尾部需外部检查点才能发现'}

    def append(self, db):
        row=db.execute('SELECT id,sid,at,action,status,detail FROM audit ORDER BY id DESC LIMIT 1').fetchone()
        prior=db.execute('SELECT seq,digest FROM review_audit_chain ORDER BY seq DESC LIMIT 1').fetchone()
        seq,prev=(prior[0]+1,prior[1]) if prior else (1,db.execute('SELECT digest FROM review_audit_baseline').fetchone()[0])
        db.execute('INSERT INTO review_audit_chain VALUES(?,?,?,?)',(seq,row[0],prev,digest({'seq':seq,'previous':prev,'row':row})))
