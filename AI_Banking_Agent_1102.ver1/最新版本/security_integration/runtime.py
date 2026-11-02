"""Preserve latest UI/quotes while replacing the web dispatch's security port."""
from live_products.runtime import LiveProductService,make_server as make_product_server
from .guardian import GuardianIntegration

class IntegratedService(LiveProductService):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.guardian=GuardianIntegration(self)
        from .login_limit import LoginLimiter
        self.login_limiter=LoginLimiter(self)

    def dispatch(self,db,state,action,args):
        # Original LedgerGateway still checks bounded arguments and operation ownership.
        # Every legacy dispatcher call now occurs only inside Guardian.execute.
        parent=super().dispatch
        return self.guardian.execute(db,state,action,args,parent)

    def authorize_cached_response(self,db,state,action,args,response):
        from first_agent.replay_access import check_replay_access
        check_replay_access(self,state,action,args,response)
        return self.guardian.execute(db,state,action,args,lambda *_:response,replay_response=response)

    def research_call(self,sid,action,args,key=None):
        from contextlib import closing
        from first_agent.service import Fault
        with closing(self.connect()) as db:
            state=self.load(db,sid)
        parent=super().research_call
        service=self
        class AuditPort:
            # Public research never holds the bank write lock while networking.
            def execute(inner,sql,params=()):
                with service.transaction() as db:
                    db.execute(sql,params)
        try:
            return self.guardian.execute(AuditPort(),state,action,args,
                lambda db,state,action,args:parent(sid,action,args,key))
        except Fault as exc:
            return self.envelope(status='rejected',error={'code':exc.code,'message':exc.message})


def make_server(service,host='127.0.0.1',port=8808):
    from .privacy import session_tag
    from urllib.parse import urlsplit
    from contextlib import closing
    from first_agent import server as original_server
    from first_agent.service import Fault
    if host not in {'127.0.0.1','localhost'}:
        raise Fault('LOCAL_ONLY','本地演示版不允许监听公网地址',403)
    server=make_product_server(service,host,port)
    original_server.APP_VERSION='AI_Banking_Agent_1101_Guardian_hardened_local_demo'
    from .transport import TransportHardening
    server.integration_service=service
    Parent=server.RequestHandlerClass
    class Handler(TransportHardening,Parent):
        def do_GET(self):
            if urlsplit(self.path).path!='/api/security/status':return super().do_GET()
            try:
                self.safe_host();sid=self.sid()
                with closing(service.connect()) as db:
                    service.load(db,sid)
                    count=db.execute('SELECT count(*) FROM guardian_dispatch WHERE sid=?',(session_tag(sid),)).fetchone()[0]
                return self.send_json(service.envelope({'mode':'local_demo','gateway':'HardenedToolGateway',
                    'business_dispatches':count,'separate_bank_ledger':False,'real_identity_verified':False}))
            except Fault as exc:
                return self.send_json(service.envelope(status='rejected',error={'code':exc.code,'message':exc.message}),exc.status)
    server.RequestHandlerClass=Handler
    return server
