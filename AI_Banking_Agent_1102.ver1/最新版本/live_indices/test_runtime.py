from copy import deepcopy
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError
from datetime import datetime
import json
import threading
import unittest
import uuid

from first_agent.market_data import market_context
from first_agent.calendar_provider import today
from .runtime import LiveIndexService, make_server, planning_script
from .provider import CN


class StubProvider:
    def __init__(self):
        self.calls = 0
        self.service = None
    def clock(self):
        return datetime(2026, 10, 30, 16, tzinfo=CN)
    def resolve(self, cards):
        self.calls += 1
        # If the banking transaction is still held this write-lock acquisition fails.
        with closing(self.service.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            db.rollback()
        result = []
        for row in deepcopy(cards):
            row.update(source='同花顺', close=1234.56, series_kind='intraday',
                       retrieved_at=self.clock().isoformat(), freshness='测试报价',
                       change_20d=None, points=[])
            result.append({'index_name': row['name'], 'index_code': row['code'],
                           'steps': [{'source': '同花顺', 'status': 'accepted'}],
                           'result_source': '同花顺', 'final_data': row})
        return result


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.provider = StubProvider()
        cls.service = LiveIndexService(Path(cls.temp.name) / 'ledger.sqlite3', index_provider=cls.provider,
                                      index_log=Path(cls.temp.name) / 'sources.jsonl')
        cls.provider.service = cls.service
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
        old = self.provider.calls
        self.assertEqual(self.request('/api/market/context')[0], 401)
        self.assertEqual(self.provider.calls, old)

    def test_context_and_page_open_use_adapter(self):
        client = self.session()
        for path, body in [('/api/market/context', None), ('/api/page/open', {})]:
            code, response = self.request(path, body, client)
            self.assertEqual(code, 200)
            context = response['data'] if body is None else response['data']['market']
            self.assertEqual(len(context['index_selection']), 9)
            self.assertEqual(context['indices'][0]['close'], 1234.56)
            self.assertEqual(context['indices'][0]['source'], '同花顺')

    def test_products_and_account_balances_unchanged(self):
        client = self.session()
        dataset = deepcopy(self.service.market_data)
        before = self.request('/api/snapshot', client=client)[1]['data']['state']
        context = self.request('/api/market/context', client=client)[1]['data']
        local = market_context(dataset, today())
        self.assertEqual(context['product_observations'], local['product_observations'])
        after = self.request('/api/snapshot', client=client)[1]['data']['state']
        self.assertEqual(before['available'], after['available'])
        self.assertEqual(dataset, self.service.market_data)

    def test_source_audit_has_eight_fields(self):
        self.request('/api/market/context', client=self.session())
        row = json.loads(self.service.index_log.read_text(encoding='utf-8').splitlines()[-1])
        self.assertEqual(set(row), {'user_id', 'intent', 'tool', 'input', 'output', 'risk_check', 'approval', 'timestamp'})

    def test_new_view_and_inherited_toolbar_both_served(self):
        script = build_opener().open(self.base + '/planning-market.js').read()
        self.assertEqual(script, planning_script())
        self.assertIn(b'window.BankIndexCards(contextData)', script)
        self.assertNotIn(b'i.close.toFixed(2)', script)
        toolbar = build_opener().open(self.base + '/review/experience.js').read()
        expected = (Path(__file__).parents[1] / 'ui_fix/toolbar.js').read_bytes()
        self.assertTrue(toolbar.endswith(expected))


if __name__ == '__main__':
    unittest.main()
