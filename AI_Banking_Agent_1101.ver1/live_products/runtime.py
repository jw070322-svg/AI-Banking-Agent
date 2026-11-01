"""Attach product quotes after the inherited banking transaction has closed."""
from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from first_agent.service import Fault
from live_indices.runtime import LiveIndexService, make_server as make_index_server
from live_indices.runtime import planning_script as index_planning_script
from .provider import ProductProvider

ROOT = Path(__file__).parent
PRODUCT_ANCHOR = '<details><summary>查看产品历史净值（'
PRODUCT_SNIPPET = '${window.BankProductQuotes(contextData)}\n'

MARKET_ACTIONS = {'market.context', 'page.open', 'market.recommend', 'calendar.google.sync'}


def planning_script():
    return index_planning_script(
        extra=(ROOT / 'cards.js', PRODUCT_ANCHOR, PRODUCT_SNIPPET))


def make_server(service, host='127.0.0.1', port=8807):
    return make_index_server(service, host, port, script=planning_script())


class LiveProductService(LiveIndexService):
    """Index quotes from the inherited adapter plus exchange-traded product prices."""

    def __init__(self, *args, product_provider=None, product_log=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.product_provider = product_provider or ProductProvider()
        self.product_log = (Path(product_log) if product_log
                            else Path(__file__).resolve().parents[1] / 'runtime/product-quote-audit.jsonl')
        self.product_log_lock = threading.Lock()

    def products(self):
        dataset = getattr(self, 'market_data', None)
        if not isinstance(dataset, dict) or not dataset.get('products'):
            return None
        return [{'code': p['code'], 'name': p['name']} for p in dataset['products'].values()]

    def call(self, sid, action, args=None, key=None):
        response = super().call(sid, action, args, key)
        if response.get('error') or action not in MARKET_ACTIONS:
            return response
        response = deepcopy(response)
        payload = response.get('data')
        context = payload if action == 'market.context' else (payload or {}).get('market')
        if not isinstance(context, dict):
            return response
        products = self.products()
        if not products:
            context['product_quote_selection'] = []
            context['product_quote_notice'] = '本地产品数据不可用，未发起任何产品行情请求。'
            return response
        try:
            rows = self.product_provider.resolve(products)
        except Exception:
            rows = []
            context['product_quote_error'] = '产品行情来源检查失败；未使用任何替代或推算价格。'
        if rows:
            context['product_quote_selection'] = rows
            context['product_quote_summary'] = {
                'attempted': len(rows),
                'priced': sum(1 for r in rows if r.get('status') == 'priced'),
                'not_applicable': sum(1 for r in rows if r.get('status') == 'not_applicable'),
                'unavailable': sum(1 for r in rows if r.get('status') == 'unavailable'),
                'participates_in_scoring': False,
            }
            context['product_quote_policy'] = ('场内ETF：同花顺公开分时；场外基金与银行理财：无公开交易行情，'
                                               '只给人工核验入口；价格不参与253点评分、排名或情景收益；60秒公共行情缓存')
            context['product_quote_notice'] = ('下表价格来自交易所公开行情，不是单位净值，不参与评分与排名；'
                                               '净值与推荐仍使用本地 Wind 快照。取不到的行情不补造。')
            self.record_quote_audit(context, rows)
        return response

    def record_quote_audit(self, context, rows):
        """Never name this ``audit``: that would shadow AgentService.audit."""
        record = {'user_id': 'local_demo', 'intent': 'display_product_quotes',
                  'tool': 'official_product_quote_priority',
                  'input': {'products': [r['product_code'] for r in rows]},
                  'output': rows,
                  'risk_check': ('HTTPS allowlist (d.10jqka.com.cn); certificate verified; no redirects; '
                                 'no page scripts executed; no client data transmitted; price excluded from scoring'),
                  'approval': 'user_requested_official_public_quotes',
                  'timestamp': self.product_provider.clock().isoformat()}
        try:
            with self.product_log_lock:
                self.product_log.parent.mkdir(parents=True, exist_ok=True)
                with self.product_log.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
        except OSError:
            context['product_quote_audit_warning'] = '产品行情审计文件暂不可写；本次来源步骤仍随响应提供。'
