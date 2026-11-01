import json
import unittest
from datetime import datetime
from pathlib import Path

from live_indices.provider import Unavailable, safe_url
from .provider import (CN, PRODUCT_HOSTS, ProductProvider, etf_token, name_overlap,
                       parse_etf_jsonp, product_type, registration_code)

NOW = datetime(2026, 10, 30, 16, 0, tzinfo=CN)
ETF = {'code': '510300.SH', 'name': '华泰柏瑞沪深300ETF'}
FUND = {'code': '000128.OF', 'name': '大成景安短融A'}
WEALTH = {'code': 'GL24651.LC', 'name': '工银理财·天天鑫稳益固定收益类开放式理财产品(24GS5090)'}
PROBE = Path(__file__).resolve().parents[1] / 'reports/product-quote-probe'


def ths(**changes):
    data = {'date': '20261030', 'pre': '4.111', 'name': '沪深300ETF华泰柏瑞',
            'data': '0930,4.059,44179780,4.059,10884400;1500,4.111,1,4.111,1'}
    data.update(changes)
    return 'quotebridge_v6_time_hs_510300_last(' + json.dumps({'hs_510300': data}) + ')'


class Transport:
    def __init__(self, data=None):
        self.data, self.calls = data or {}, []

    def __call__(self, url):
        self.calls.append(url)
        value = self.data.get(url, Unavailable('测试网络不可用'))
        if isinstance(value, Exception):
            raise value
        return value


class GateTests(unittest.TestCase):
    def test_only_exchange_segments_are_eligible(self):
        self.assertEqual(etf_token('510300.SH'), '510300')
        self.assertEqual(etf_token('159928.SZ'), '159928')
        # 场外基金代码与股票同号，绝不能进入行情路径（000078 -> ST海王）。
        self.assertIsNone(etf_token('000078.OF'))
        self.assertIsNone(etf_token('003009.OF'))
        self.assertIsNone(etf_token('600519.SH'))
        self.assertIsNone(etf_token('000001.SZ'))
        self.assertIsNone(etf_token('GL24651.LC'))

    def test_product_type(self):
        self.assertEqual(product_type('510300.SH'), 'exchange_traded')
        self.assertEqual(product_type('000128.OF'), 'open_end_fund')
        self.assertEqual(product_type('GL24651.LC'), 'bank_wealth')

    def test_registration_code_only_from_name(self):
        self.assertEqual(registration_code(WEALTH['name']), '24GS5090')
        self.assertIsNone(registration_code('阳光金增利稳健天天购定制(1年最低持有)'))

    def test_name_overlap(self):
        self.assertGreater(name_overlap('华泰柏瑞沪深300ETF', '沪深300ETF华泰柏瑞'), 0.9)
        self.assertLess(name_overlap('华泰柏瑞沪深300ETF', '上证50ETF华夏'), 0.5)


class ParseTests(unittest.TestCase):
    def test_real_fixture(self):
        text = (PROBE / 'etf_510300_last.txt').read_text(encoding='utf-8')
        quote = parse_etf_jsonp(text, '510300', NOW, ETF['name'])
        self.assertEqual(quote['price_basis'], 'exchange_traded_price')
        self.assertGreater(len(quote['points']), 200)
        self.assertTrue(quote['as_of'].startswith('2026-10-30'))

    def test_synthetic_quote(self):
        quote = parse_etf_jsonp(ths(), '510300', NOW, ETF['name'])
        self.assertAlmostEqual(quote['price'], 4.111)
        self.assertAlmostEqual(quote['previous_close'], 4.111)
        self.assertEqual(quote['series_kind'], 'intraday')

    def test_callback_and_key_must_match_exactly(self):
        with self.assertRaises(Unavailable):
            parse_etf_jsonp(ths().replace('hs_510300', 'hs_510050'), '510300', NOW, ETF['name'])
        with self.assertRaises(Unavailable):
            parse_etf_jsonp(ths() + ';alert(1)', '510300', NOW, ETF['name'])

    def test_name_mismatch_rejected(self):
        with self.assertRaises(Unavailable):
            parse_etf_jsonp(ths(name='上证50ETF华夏'), '510300', NOW, ETF['name'])

    def test_bad_rows_fail_closed(self):
        for payload in [ths(data=''), ths(pre='0'), ths(pre='-1'),
                        ths(data='0930,4.0,1,4.0,1;0930,4.1,1,4.1,1'),
                        ths(data='0930,nan,1,nan,1'), ths(data='0930,-1,1,-1,1'),
                        ths(date='20991231'), ths(date='20200101')]:
            with self.assertRaises(Unavailable, msg=payload[:60]):
                parse_etf_jsonp(payload, '510300', NOW, ETF['name'])


class ResolveTests(unittest.TestCase):
    def provider(self, responses=None):
        fetch = Transport(responses)
        return ProductProvider(fetch, lambda: NOW), fetch

    def test_of_and_lc_never_request(self):
        provider, fetch = self.provider()
        rows = provider.resolve([FUND, WEALTH])
        self.assertEqual(fetch.calls, [])
        self.assertEqual([r['status'] for r in rows], ['not_applicable', 'not_applicable'])
        self.assertIn('24GS5090', rows[1]['verification_url'])

    def test_fund_collision_regression(self):
        provider, fetch = self.provider()
        provider.resolve([{'code': '000078.OF', 'name': '工银信用纯债三个月定开债A'}])
        self.assertEqual(fetch.calls, [])

    def test_priced_row_shape(self):
        provider, fetch = self.provider({'https://d.10jqka.com.cn/v6/time/hs_510300/last.js': ths()})
        row = provider.resolve([ETF])[0]
        self.assertEqual(row['status'], 'priced')
        self.assertFalse(row['participates_in_scoring'])
        data = row['final_data']
        self.assertEqual(data['price'], 4.111)
        self.assertNotIn('latest_nav', data)
        self.assertEqual(fetch.calls, ['https://d.10jqka.com.cn/v6/time/hs_510300/last.js'])

    def test_unavailable_row_has_no_fabricated_price(self):
        provider, _ = self.provider({'https://d.10jqka.com.cn/v6/time/hs_510300/last.js': Unavailable('HTTP 502')})
        row = provider.resolve([ETF])[0]
        self.assertEqual(row['status'], 'unavailable')
        self.assertIsNone(row['final_data'])
        self.assertTrue(row['error'])

    def test_all_three_types_in_one_run(self):
        provider, _ = self.provider({'https://d.10jqka.com.cn/v6/time/hs_510300/last.js': ths()})
        rows = provider.resolve([ETF, FUND, WEALTH])
        self.assertEqual([r['status'] for r in rows], ['priced', 'not_applicable', 'not_applicable'])

    def test_cache_reuse_keeps_fetch_time(self):
        provider, fetch = self.provider({'https://d.10jqka.com.cn/v6/time/hs_510300/last.js': ths()})
        first = provider.resolve([ETF])[0]
        second = provider.resolve([ETF])[0]
        self.assertEqual(len(fetch.calls), 1)
        self.assertTrue(second['cache']['reused'])
        self.assertEqual(first['final_data']['retrieved_at'], second['final_data']['retrieved_at'])


class BoundaryTests(unittest.TestCase):
    def test_allowlist_is_parameterised(self):
        safe_url('https://d.10jqka.com.cn/v6/time/hs_510300/last.js', PRODUCT_HOSTS)
        # 指数白名单更宽：同样的 URL 默认放行，产品侧只允许行情域名。
        safe_url('https://q.10jqka.com.cn/zs/')
        with self.assertRaises(Unavailable):
            safe_url('https://q.10jqka.com.cn/zs/', PRODUCT_HOSTS)
        for bad in ['https://q.10jqka.com.cn/zs/', 'http://d.10jqka.com.cn/x',
                    'https://d.10jqka.com.cn.evil.test/x', 'https://127.0.0.1/x']:
            with self.assertRaises(Unavailable):
                safe_url(bad, PRODUCT_HOSTS)

    def test_requests_carry_no_customer_data(self):
        provider = ProductProvider(Transport({'https://d.10jqka.com.cn/v6/time/hs_510300/last.js': ths()}))
        provider.resolve([ETF])
        for url in provider.fetch.calls:
            self.assertTrue(url.startswith('https://d.10jqka.com.cn/v6/time/hs_'))
            self.assertNotIn('?', url)


if __name__ == '__main__':
    unittest.main()
