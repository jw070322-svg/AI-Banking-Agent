"""Reproduce protocol findings against the inherited pre-hardening HTTP handler.
Only read authorization and summary calls; no financial operation is submitted.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.request import build_opener,HTTPCookieProcessor,Request
import json,uuid
from start import prepare_node
from live_products.runtime import make_server
from security_integration.runtime import IntegratedService

def main():
    prepare_node()
    with TemporaryDirectory() as temp:
        server=make_server(IntegratedService(Path(temp)/'baseline.sqlite3'),port=0)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        client=build_opener(HTTPCookieProcessor());base='http://127.0.0.1:'+str(server.server_port)
        def call(path,body=None,ctype='application/json'):
            raw=body if isinstance(body,str) else json.dumps(body) if body is not None else None
            headers={'Content-Type':ctype,'Idempotency-Key':uuid.uuid4().hex} if raw is not None else {}
            with client.open(Request(base+path,data=raw.encode() if raw is not None else None,headers=headers)) as response:
                return response.status,dict(response.headers),json.loads(response.read())
        try:
            call('/api/session',{})
            call('/api/rpc',{'method':'authorize','args':[{'read':True,'trade':False,'subscriptions':False,'cards':False}]})
            duplicate=call('/api/rpc','{"method":"arbitraryTool","method":"summary","args":[]}')
            content=call('/api/rpc',{'method':'summary','args':[]},'text/plain; application/json')
            health=call('/api/health')
            result={'scope':'inherited HTTP parent without TransportHardening, isolated local fixture',
                'duplicate_json_accepted':duplicate[0]==200 and duplicate[2]['error'] is None,
                'fake_content_type_accepted':content[0]==200 and content[2]['error'] is None,
                'health_discloses_directory':'directory' in health[2]['data'].get('analysis',{}),
                'frame_protection_header_present':'X-Frame-Options' in health[1],
                'financial_operations_submitted':0}
            assert result['duplicate_json_accepted'] and result['fake_content_type_accepted'] and result['health_discloses_directory']
            out=Path(__file__).resolve().parents[1]/'reports/security-integration-1101/baseline-findings.json'
            out.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(result)
        finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()
