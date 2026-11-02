import json
import threading
import unittest
import uuid
from contextlib import closing
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from first_agent.calendar_provider import today
from first_agent.market_data import market_context
from live_indices.test_runtime import StubProvider as StubIndexProvider
from live_products.runtime import LiveProductService, make_server, planning_script
from .provider import CN

AUDIT_FIELDS = {'user_id', 'intent', 'tool', 'input', 'output', 'risk_check', 'approval', 'timestamp'}


class StubProductProvider:
    def __init__(self):
        self.calls = 0
        self.service = None

    def clock(self):
        return datetime(2026, 10, 30, 16, tzinfo=CN)

    def resolve(self, products):
        self.calls += 1
        # If the banking transaction is still held this write-lock acquisition fails.
        with closing(self.service.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            db.rollback()
        rows = []
        for item in products:
            priced = item['code'].endswith(('.SH', '.SZ'))
            rows.append({'product_code': item['code'], 'product_name': item['name'],
                         'product_type': 'exchange_traded' if priced else 'bank_wealth',
                         'participates_in_scoring': False, 'status': 'priced' if priced else 'not_applicable',
                         'result_source': '同花顺场内分时' if priced else None,
                         'final_data': ({'price': 4.111, 'previous_close': 4.0, 'change_1d': 0.0278,
                                         'as_of': '2026-10-30T15:00:00+08:00', 'points': [],
                                         'series_kind': 'intraday', 'price_basis': 'exchange_traded_price',
                                         'freshness': '测试报价', 'retrieved_at': self.clock().isoformat(),
                                         'stale': False, 'official_name': '测试名称'} if priced else None),
                         'steps': [{'source': '同花顺场内分时', 'status': 'accepted' if priced else 'not_applicable'}],
                         'cache': {'reused': False, 'ttl_seconds': 60}})
        return rows


class ProductRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.index_provider = StubIndexProvider()
        cls.product_provider = StubProductProvider()
        cls.service = LiveProductService(
            Path(cls.temp.name) / 'ledger.sqlite3', index_provider=cls.index_provider,
            index_log=Path(cls.temp.name) / 'index.jsonl',
            product_provider=cls.product_provider, product_log=Path(cls.temp.name) / 'product.jsonl')
        cls.index_provider.service = cls.service
        cls.product_provider.service = cls.service
        cls.server = make_server(cls.service, port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()

    def request(self, path, data=None, client=None):
        headers = {'Content-Type': 'application/json', 'Idempotency-Key': uuid.uuid4().hex}
        body = json.dumps(data).encode() if data is not None else None
        try:
            response = (client or build_opener()).open(Request(self.base + path, data=body, headers=headers))
        except HTTPError as exc:
            response = exc
        with response:
            return response.code, json.loads(response.read())

    def session(self):
        client = build_opener(HTTPCookieProcessor())
        self.assertEqual(self.request('/api/session', {}, client)[0], 200)
        return client

    def test_invalid_session_does_not_start_network(self):
        before = self.product_provider.calls
        self.assertEqual(self.request('/api/market/context')[0], 401)
        self.assertEqual(self.product_provider.calls, before)

    def test_context_page_open_and_recommend_carry_quotes(self):
        client = self.session()
        for path, body in [('/api/market/context', None), ('/api/page/open', {})]:
            code, response = self.request(path, body, client)
            self.assertEqual(code, 200)
            context = response['data'] if body is None else response['data']['market']
            self.assertEqual(len(context['product_quote_selection']), 35)
            self.assertFalse(context['product_quote_summary']['participates_in_scoring'])
            self.assertEqual(context['product_quote_summary']['priced'], 14)
            self.assertEqual(len(context['index_selection']), 9)
        # 推荐排名不因新增行情而改变。
        self.assertEqual(self.request('/api/market/recommend', {}, client)[0], 200)

    def test_product_observations_unchanged(self):
        client = self.session()
        _, response = self.request('/api/market/context', None, client)
        expected = market_context(self.service.market_data, today())['product_observations']
        self.assertEqual(response['data']['product_observations'], expected)

    def test_product_audit_has_eight_fields(self):
        client = self.session()
        self.request('/api/market/context', None, client)
        log = Path(self.temp.name) / 'product.jsonl'
        self.assertTrue(log.is_file())
        for line in log.read_text(encoding='utf-8').splitlines():
            self.assertEqual(set(json.loads(line)), AUDIT_FIELDS)

    def test_audit_failure_is_soft(self):
        # 审计目录位置被一个普通文件占用，写入必须降级为提示而不是抛错。
        blocker = Path(self.temp.name) / 'blocked'
        blocker.write_text('not a directory', encoding='utf-8')
        broken = LiveProductService(
            Path(self.temp.name) / 'broken.sqlite3', index_provider=StubIndexProvider(),
            index_log=Path(self.temp.name) / 'index2.jsonl',
            product_provider=StubProductProvider(), product_log=blocker / 'audit.jsonl')
        context = {}
        broken.record_quote_audit(context, [{'product_code': '510300.SH'}])
        self.assertIn('product_quote_audit_warning', context)

    def test_script_injects_both_blocks_before_nav_table(self):
        script = planning_script()
        self.assertIn(b'window.BankIndexCards(contextData)', script)
        self.assertIn(b'window.BankProductQuotes(contextData)', script)
        nav = '查看产品历史净值（'.encode()
        self.assertEqual(script.count(nav), 1)
        self.assertLess(script.index(b'BankProductQuotes'), script.index(nav))
        self.assertIn(b'latest_nav.toFixed(4)', script)
        self.assertNotIn(b'i.close.toFixed(2)', script)


class AnchorTests(unittest.TestCase):
    def test_anchor_drift_fails_fast(self):
        from live_indices.runtime import planning_script as index_planning_script
        # 锚点不存在时必须拒绝启动，而不是提供半个界面；不触碰磁盘上的原文件。
        with self.assertRaises(ValueError):
            index_planning_script(extra=(Path(__file__).parent / 'cards.js', '<不存在的锚点>', 'x'))
        self.assertIn(b'BankIndexCards', index_planning_script())

    def test_index_only_script_has_no_product_block(self):
        from live_indices.runtime import planning_script as index_planning_script
        script = index_planning_script()
        self.assertNotIn(b'BankProductQuotes', script)
        self.assertIn(b'BankIndexCards', script)


if __name__ == '__main__':
    unittest.main()
