"""Read-only audit verification with optional separately kept checkpoint."""
import argparse,json,sqlite3
from pathlib import Path
from .audit_chain import AuditChain
from first_agent.service import Fault

def verify(database, checkpoint=None):
    path=Path(database).resolve()
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('BEGIN')
        result=AuditChain.__new__(AuditChain).verify(db)
        if checkpoint:
            prior=json.loads(Path(checkpoint).read_text(encoding='utf-8'))
            if prior['entries']>result['entries'] or prior['baseline_last_id']!=result['baseline_last_id']:
                raise Fault('AUDIT_ROLLBACK','记录早于已保存检查点')
            saved=db.execute('SELECT digest FROM review_audit_chain WHERE seq=?',(prior['entries'],)).fetchone() if prior['entries'] else db.execute('SELECT digest FROM review_audit_baseline').fetchone()
            if not saved or saved[0]!=prior['head']:raise Fault('AUDIT_ROLLBACK','记录与外部保留检查点不一致')
        return result
    finally:db.close()

def main():
    p=argparse.ArgumentParser(description='只读核验本地审计链；检查点应另行保管，不是生产审计认证')
    p.add_argument('--db',required=True);p.add_argument('--checkpoint');p.add_argument('--save-checkpoint')
    a=p.parse_args()
    try:
        result=verify(a.db,a.checkpoint)
        if a.save_checkpoint:
            # Never silently replace a trusted anchor with a newer, potentially rolled-back state.
            with open(a.save_checkpoint,'x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (Fault,ValueError,OSError,sqlite3.Error) as exc:p.exit(1,getattr(exc,'message',str(exc))+'\n')
if __name__=='__main__':main()
