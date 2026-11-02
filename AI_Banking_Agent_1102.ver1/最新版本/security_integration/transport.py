"""Unambiguous JSON framing and response isolation for the local HTTP entry."""
import io,json,re
from urllib.parse import urlsplit
from first_agent.service import Fault

def unique_object(pairs):
    obj={}
    for k,v in pairs:
        if k in obj:raise ValueError('duplicate key')
        obj[k]=v
    return obj

class TransportHardening:
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def end_headers(self):
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
        self.send_header('Content-Security-Policy',"frame-ancestors 'none'; object-src 'none'; base-uri 'self'")
        super().end_headers()

    def send_json(self,value,status=200,cookie=None):
        if urlsplit(self.path).path in {'/api/health','/api/analysis/status'} and isinstance(value.get('data'),dict):
            from copy import deepcopy
            value=deepcopy(value)
            analysis=value['data'].get('analysis') if urlsplit(self.path).path=='/api/health' else value['data']
            if isinstance(analysis,dict):analysis.pop('directory',None)
        return super().send_json(value,status,cookie)

    def do_POST(self):
        original=self.rfile
        try:
            self.safe_host()
            if self.headers.get('Transfer-Encoding'):
                raise Fault('REQUEST_FRAMING','不支持该请求传输格式',400)
            lengths=self.headers.get_all('Content-Length',[])
            if len(lengths)!=1 or not re.fullmatch(r'[0-9]{1,7}',lengths[0]):
                raise Fault('REQUEST_FRAMING','请求长度格式不正确',400)
            size=int(lengths[0])
            if not 0<size<=65536:raise Fault('PAYLOAD_SIZE','请求体超过允许大小',413)
            if len(self.headers.get_all('Content-Type',[]))!=1 or self.headers.get_content_type()!='application/json':
                raise Fault('CONTENT_TYPE','需要 application/json',415)
            raw=self.rfile.read(size)
            if len(raw)!=size:raise Fault('INVALID_JSON','请求内容不完整',400)
            try:
                value=json.loads(raw,object_pairs_hook=unique_object,
                    parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
                if not isinstance(value,dict):raise ValueError()
            except (ValueError,UnicodeError,RecursionError):
                raise Fault('INVALID_JSON','请求格式不正确，不能包含重复字段或非标准数值',400)
            if urlsplit(self.path).path=='/api/developer/login':
                self.server.integration_service.login_limiter.consume(self.sid(),self.client_address[0])
            # Delegate the unchanged handler using exactly the already checked body.
            self.rfile=io.BytesIO(raw)
            return super().do_POST()
        except Fault as exc:
            self.close_connection=True
            return self.send_json(self.server.integration_service.envelope(status='rejected',
                error={'code':exc.code,'message':exc.message}),exc.status)
        except (TimeoutError,OSError):
            self.close_connection=True
            return self.send_json(self.server.integration_service.envelope(status='rejected',
                error={'code':'REQUEST_TIMEOUT','message':'请求读取超时或连接中断，请重试'}),408)
        finally:self.rfile=original
