"""Attach public quotes only after the inherited banking transaction has closed."""
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
import json
import threading

from first_agent.service import Fault
from relay_additions.runtime import RelayService
from ui_fix.server import make_server as make_ui_server
from .provider import IndexProvider

ROOT = Path(__file__).parent


def planning_script(extra=None):
    """Serve the index view; ``extra`` optionally adds one more client-side block.

    ``extra`` is ``(js_path, anchor, snippet)``: the snippet is inserted *before*
    the anchor so the inherited markup at that anchor stays untouched. Anchors
    must stay unique, otherwise the adapter refuses to start rather than serve a
    half-migrated page.
    """
    raw = (ROOT.parent / 'web/planning-market.js').read_text(encoding='utf-8')
    start = raw.index('<div class="index-grid">')
    end = raw.index('\n${(contextData?.macro', start)
    if raw.count('<div class="index-grid">') != 1:
        raise ValueError('Inherited index card anchor changed; review adapter before starting')
    # Replace one view fragment in the served response; inherited source stays byte-identical.
    raw = raw[:start] + '${window.BankIndexCards(contextData)}' + raw[end:]
    prefix = (ROOT / 'cards.js').read_bytes()
    if extra:
        js_path, anchor, snippet = extra
        if raw.count(anchor) != 1:
            raise ValueError('Inherited product anchor changed; review adapter before starting')
        cut = raw.index(anchor)
        raw = raw[:cut] + snippet + raw[cut:]
        prefix += b'\n;\n' + Path(js_path).read_bytes()
    return prefix + b'\n;\n' + raw.encode('utf-8')


class LiveIndexService(RelayService):
    def __init__(self, *args, index_provider=None, index_log=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.index_provider = index_provider or IndexProvider()
        self.index_log = Path(index_log) if index_log else ROOT.parent / 'runtime/index-source-audit.jsonl'
        self.index_log_lock = threading.Lock()

    def call(self, sid, action, args=None, key=None):
        response = super().call(sid, action, args, key)
        if response.get('error') or action not in {'market.context', 'page.open', 'market.recommend', 'calendar.google.sync'}:
            return response
        response = deepcopy(response)
        payload = response.get('data')
        context = payload if action == 'market.context' else (payload or {}).get('market')
        if not isinstance(context, dict) or not isinstance(context.get('indices'), list):
            return response
        # No user inputs, holdings, budget, session ID or financial product records leave the host.
        rows = self.index_provider.resolve(context['indices'])
        context['index_selection'] = rows
        context['indices'] = [deepcopy(row['final_data']) for row in rows if row['final_data']]
        context['index_policy'] = '同花顺 → Wind官网 → 本地wind数据表格；每指数独立；60秒公共行情缓存'
        context['headline'] = '【本地历史研究依据】' + context.get('headline', '')
        context['index_notice'] = '下方指数联网优先；上方概述、宏观和产品推荐仍使用原有历史研究口径。分时接口不提供20日涨跌幅，不混用本地值。'
        record = {'user_id': 'local_demo', 'intent': 'display_index_quotes', 'tool': 'official_index_priority',
                  'input': {'indices': [r['index_code'] for r in rows]}, 'output': rows,
                  'risk_check': 'HTTPS allowlist; certificate verified; no client data transmitted; no model/tools executed',
                  'approval': 'user_requested_official_public_quotes', 'timestamp': self.index_provider.clock().isoformat()}
        try:
            with self.index_log_lock:
                self.index_log.parent.mkdir(parents=True, exist_ok=True)
                with self.index_log.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
        except OSError:
            context['index_audit_warning'] = '指数来源审计文件暂不可写；本次来源步骤仍随响应提供。'
        return response


def make_server(service, host='127.0.0.1', port=8806, script=None):
    if script is None:
        script = planning_script()  # Fail early for incompatible UI; never serve a partly migrated view.
    server = make_ui_server(service, host, port)
    Parent = server.RequestHandlerClass

    class Handler(Parent):
        def do_GET(self):
            if urlsplit(self.path).path != '/planning-market.js':
                return super().do_GET()
            try:
                self.safe_host()
                self.send_bytes(script, 'text/javascript; charset=utf-8')
            except Fault as exc:
                self.send_json(service.envelope(status='rejected', error={'code': exc.code, 'message': exc.message}), exc.status)
    server.RequestHandlerClass = Handler
    return server
