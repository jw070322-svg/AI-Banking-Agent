from pathlib import Path
from urllib.parse import urlsplit
from first_agent.service import Fault
from review_additions.runtime import ROOT as REVIEW_ROOT
from relay_additions import runtime as relay

ROOT = Path(__file__).parent


def make_server(service, host='127.0.0.1', port=8804):
    server = relay.make_server(service, host, port)
    Parent = server.RequestHandlerClass

    class Handler(Parent):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path not in {'/review/experience.js', '/review/experience.css'}:
                return super().do_GET()
            try:
                self.safe_host()
                if path.endswith('.js'):
                    body = (REVIEW_ROOT/'experience.js').read_bytes() + b'\n;\n' + (ROOT/'toolbar.js').read_bytes()
                    kind = 'text/javascript; charset=utf-8'
                else:
                    body = (REVIEW_ROOT/'experience.css').read_bytes() + b'\n' + (ROOT/'toolbar.css').read_bytes()
                    kind = 'text/css; charset=utf-8'
                self.send_bytes(body, kind)
            except Fault as exc:
                self.send_json(service.envelope(status='rejected', error={'code':exc.code,'message':exc.message}),exc.status)

    server.RequestHandlerClass = Handler
    return server
