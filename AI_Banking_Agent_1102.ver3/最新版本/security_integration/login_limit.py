"""Bound local demo login attempts; not a substitute for real authentication."""
from first_agent.service import Fault
from .privacy import session_tag

class LoginLimiter:
    def __init__(self,service):
        self.service=service
        with service.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS security_login_limits(bucket TEXT PRIMARY KEY,window REAL,attempts INTEGER)')
    def consume(self,sid,address):
        now=self.service.clock()
        with self.service.transaction() as db:
            self.service.load(db,sid)
            for bucket,limit in [(session_tag(sid),5),('address:'+address,20)]:
                row=db.execute('SELECT window,attempts FROM security_login_limits WHERE bucket=?',(bucket,)).fetchone()
                start,count=(row[0],row[1]) if row and 0<=now-row[0]<60 else (now,0)
                if count>=limit:raise Fault('LOGIN_RATE_LIMIT','尝试过于频繁，请稍后再试',429)
                db.execute('INSERT OR REPLACE INTO security_login_limits VALUES(?,?,?)',(bucket,start,count+1))
            db.execute('DELETE FROM security_login_limits WHERE window<?',(now-120,))
