"""Loopback-only, standard-library HTTP API and teammate UI host."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote
import argparse, json, mimetypes
from .service import AgentService, Fault, BASE
from .analysis_bridge import analysis_status
from . import developer
APP_VERSION="AI_Banking_Agent_1027.ver5"
SESSION_COOKIE="banking_session_1027_v5"

def make_server(service,host='127.0.0.1',port=8768):
    developer.setup(service)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send_json(self,value,status=200,cookie=None):
            raw=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            if cookie:self.send_header('Set-Cookie',f'{SESSION_COOKIE}={cookie}; HttpOnly; SameSite=Strict; Path=/')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def sid(self):
            cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
            token=cookies.get(SESSION_COOKIE)
            if not token:raise Fault('AUTH_REQUIRED','请先建立本地演示会话',401)
            return token.value
        def safe_host(self):
            expected=f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') not in {expected,f'localhost:{self.server.server_port}'}:
                raise Fault('HOST_DENIED','只接受本机访问',403)
            origin=self.headers.get('Origin')
            if origin and origin not in {f'http://{expected}',f'http://localhost:{self.server.server_port}'}:
                raise Fault('ORIGIN_DENIED','请求来源不匹配',403)
        def do_GET(self):
            try:
                self.safe_host();url=urlsplit(self.path);path=url.path
                if path=='/api/health':return self.send_json(service.envelope({'ready':True,'persistent':True,'mode':'local_demo','app_version':APP_VERSION,'analysis':analysis_status()}))
                if path.startswith('/api/'):
                    routes={'/api/snapshot':'snapshot','/api/accounts/overview':'accounts','/api/transactions':'transactions',
                            '/api/subscriptions':'subscriptions','/api/products':'recommend','/api/events':'events',
                            '/api/analysis':'analysis','/api/analysis/status':'analysis.status','/api/calendar':'calendar.list','/api/market/status':'market.status','/api/market/context':'market.context','/api/recipients':'recipients','/api/audit/export':'audit.export'}
                    routes.update({'/api/external/status':'external.status'})
                    if path.startswith('/api/operations/'):
                        action='operation';args={'operation_id':path.rsplit('/',1)[1]}
                    else:
                        action=routes.get(path);args={k:v[-1] for k,v in parse_qs(url.query).items()}
                    if not action:raise Fault('NOT_FOUND','接口不存在',404)
                    if action=='analysis':
                        tool=args.pop('tool','analysis.pipeline');args={'tool':tool,'args':args}
                    return self.send_json(service.call(self.sid(),action,args))
                relative=unquote(path).lstrip('/') or 'index.html' 
                target=(BASE/'web'/relative).resolve()
                if not target.is_relative_to((BASE/'web').resolve()) or not target.is_file():raise Fault('NOT_FOUND','文件不存在',404)
                raw=target.read_bytes();ctype=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
                self.send_response(200);self.send_header('Content-Type',ctype+('; charset=utf-8' if ctype.startswith('text/') else ''))
                self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            except Fault as e:self.send_json(service.envelope(status='rejected',error={'code':e.code,'message':e.message}),e.status)
            except Exception:self.send_json(service.envelope(status='failed',error={'code':'INTERNAL_ERROR','message':'本地服务异常，未返回内部信息'}),500)
        def do_POST(self):
            try:
                self.safe_host()
                if 'application/json' not in self.headers.get('Content-Type',''):raise Fault('CONTENT_TYPE','需要 application/json',415)
                path=urlsplit(self.path).path
                size=int(self.headers.get('Content-Length','0'));maximum=65536
                if not 0<size<=maximum:raise Fault('PAYLOAD_SIZE','请求体超过允许大小',413)
                args=json.loads(self.rfile.read(size),parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
                if not isinstance(args,dict):raise Fault('INVALID_ARGUMENT','请求体必须为对象')
                path=urlsplit(self.path).path
                if path=='/api/session':
                    # Reuse a valid existing session; reload must preserve its ledger.
                    try:
                        sid=self.sid()
                        with service.transaction() as db:service.load(db,sid)
                    except Fault:sid=service.create_session()
                    return self.send_json(service.envelope({'mode':'local_demo'}),cookie=sid)
                if path.startswith('/api/developer/'):
                    return self.send_json(developer.call(service,self.sid(),path.rsplit('/',1)[1],args,self.headers.get('X-Developer-Token')))
                dev_method=args.get('method') if path=='/api/rpc' else None
                params=args.get('args',[])
                needs_dev=dev_method in {'advance','setProfile'} or (dev_method=='execute' and len(params)>1 and params[1]!='success') or (dev_method=='reconcile' and len(params)>1 and params[1]!='pending') or (path=='/api/transfers/reconcile' and args.get('result')!='pending') or (path=='/api/transfers/confirm' and args.get('outcome','success')!='success')
                if needs_dev:developer.validate(service,self.sid(),self.headers.get('X-Developer-Token'))
                routes={'/api/scenarios/generate':'scenario.generate','/api/analysis':'analysis','/api/rpc':'rpc','/api/chat':'chat','/api/knowledge':'knowledge','/api/recommendations':'recommend',
                        '/api/transfers/preview':'transfer.preview','/api/transfers/verify':'transfer.verify',
                        '/api/transfers/confirm':'transfer.confirm','/api/transfers/reconcile':'transfer.reconcile','/api/transfers/cancel':'transfer.cancel','/api/page/open':'page.open','/api/calendar/save':'calendar.save','/api/calendar/reserve':'calendar.reserve','/api/calendar/release':'calendar.release','/api/calendar/google/sync':'calendar.google.sync','/api/profile':'profile.update','/api/market/recommend':'market.recommend'}
                routes.update({'/api/external/probe':'external.probe','/api/external/search':'external.search','/api/local-life/links':'local_life.links'})
                action=routes.get(path)
                if not action:raise Fault('NOT_FOUND','接口不存在',404)
                key=self.headers.get('Idempotency-Key')
                if not key:raise Fault('IDEMPOTENCY_REQUIRED','POST 操作需要 Idempotency-Key')
                return self.send_json(service.call(self.sid(),action,args,key))
            except Fault as e:self.send_json(service.envelope(status='rejected',error={'code':e.code,'message':e.message}),e.status)
            except (ValueError,TypeError):self.send_json(service.envelope(status='rejected',error={'code':'INVALID_JSON','message':'JSON 格式错误'}),400)
            except Exception:self.send_json(service.envelope(status='failed',error={'code':'INTERNAL_ERROR','message':'本地服务异常，请查询原操作回执'}),500)
    return ThreadingHTTPServer((host,port),Handler)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8768);parser.add_argument('--db')
    options=parser.parse_args();server=make_server(AgentService(options.db),port=options.port)
    print(f'Local simulated banking Agent: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
