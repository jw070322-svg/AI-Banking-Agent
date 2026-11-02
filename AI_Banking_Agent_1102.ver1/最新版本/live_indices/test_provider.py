import json
from datetime import datetime
from pathlib import Path
import unittest
from .provider import (CN, THS, WIND, WIND_SCRIPT, IndexProvider, Unavailable,
                       parse_ths, parse_wind, safe_url)

NOW = datetime(2026, 10, 30, 16, 0, tzinfo=CN)
CODE = '000016.SH'
SPEC = (CODE, '上证50指数')
QUOTE_URL = 'https://d.10jqka.com.cn/v6/time/zs_1B0016/last.js'
FRAME = 'https://index_api.wind.com.cn/indexofficialwebsite/view/index.html?id=2'
LOCAL = {'code': CODE, 'name': SPEC[1], 'close': 2700.0, 'as_of': '2026-10-26',
         'source': 'Wind', 'change_1d': .01, 'change_20d': .02, 'points': [], 'stale': False}


def ths(**changes):
    data = {'date': '20261030', 'pre': '2800', 'name': '上证50',
            'data': '0930,2810,0;1500,2820,0'}
    data.update(changes)
    return 'quotebridge_v6_time_zs_1B0016_last(' + json.dumps({'zs_1B0016': data}) + ')'


def wind(**changes):
    data = {'code': CODE, 'close': 2820, 'previous_close': 2800, 'as_of': '2026-10-30T15:00:00+08:00'}
    data.update(changes)
    return json.dumps(data)


class Transport:
    def __init__(self, data):
        self.data, self.calls = data, []
    def __call__(self, url):
        self.calls.append(url)
        value = self.data.get(url, Unavailable('测试网络不可用'))
        if isinstance(value, Exception):
            raise value
        return value


class ProviderTests(unittest.TestCase):
    def provider(self, data):
        fetch = Transport(data)
        return IndexProvider(fetch, lambda: NOW), fetch

    def test_first_source_stops_chain(self):
        provider, fetch = self.provider({THS: '/zs/detail/code/1B0016/', QUOTE_URL: ths()})
        row = provider.select(SPEC, LOCAL)
        self.assertEqual(row['result_source'], '同花顺')
        self.assertEqual(len(row['steps']), 1)
        self.assertNotIn(WIND, fetch.calls)
        self.assertEqual(row['final_data']['close'], 2820)
        self.assertIsNone(row['final_data']['change_20d'])

    def test_second_source_after_first_failure(self):
        provider, fetch = self.provider({WIND: wind()})
        row = provider.select(SPEC, LOCAL)
        self.assertEqual(fetch.calls, [THS, WIND])
        self.assertEqual(row['result_source'], 'Wind官网')

    def test_real_wind_script_route_and_tls_failure(self):
        script = (Path(__file__).parents[1] / 'reports/live-index-probe/script2.txt').read_text(encoding='utf-8')
        provider, fetch = self.provider({WIND: '<iframe id="main"></iframe>', WIND_SCRIPT: script})
        row = provider.select(SPEC, LOCAL)
        self.assertEqual(row['result_source'], '本地wind数据表格')
        self.assertTrue(fetch.calls[-1].startswith('https://index_api.wind.com.cn/'))

    def test_fallback_only_after_both(self):
        provider, fetch = self.provider({})
        row = provider.select(SPEC, LOCAL)
        self.assertEqual(fetch.calls, [THS, WIND])
        self.assertEqual([s['source'] for s in row['steps']], ['同花顺', 'Wind官网', '本地wind数据表格'])
        self.assertEqual(row['final_data']['as_of'], LOCAL['as_of'])
        self.assertEqual(LOCAL['source'], 'Wind')

    def test_all_unavailable_null(self):
        provider, _ = self.provider({})
        row = provider.select(SPEC, None)
        self.assertIsNone(row['final_data'])
        self.assertIn('error', row)

    def test_each_index_independent(self):
        provider, _ = self.provider({THS: '/zs/detail/code/1B0016/', QUOTE_URL: ths()})
        rows = provider.resolve([LOCAL], [SPEC, ('931186.CSI', '中证科技50策略指数')])
        self.assertEqual(rows[0]['result_source'], '同花顺')
        self.assertEqual(len(rows[1]['steps']), 3)

    def test_cache_preserves_fetch_time(self):
        provider, fetch = self.provider({THS: '/zs/detail/code/1B0016/', QUOTE_URL: ths()})
        first = provider.resolve([LOCAL]); count = len(fetch.calls)
        second = provider.resolve([LOCAL])
        self.assertEqual(len(fetch.calls), count)
        self.assertTrue(second[0]['cache']['reused'])
        self.assertEqual(first[0]['final_data']['retrieved_at'], second[0]['final_data']['retrieved_at'])

    def test_bad_quotes_fail_closed(self):
        for changes in [{'date': '20261031'}, {'date': '20260901'}, {'date': ''},
                        {'data': '0930,nan'}, {'data': '0930,-1'}, {'data': '0930,0'},
                        {'data': '1500,2810;0930,2820'}, {'pre': 0}, {'data': ''}]:
            with self.subTest(changes=changes), self.assertRaises(Unavailable):
                parse_ths(ths(**changes), '1B0016', NOW)

    def test_wrong_instrument_and_script_injection(self):
        for text in [ths().replace('zs_1B0016', 'zs_1B0300'), ths() + ';alert(1)', '<html>2742.11</html>']:
            with self.assertRaises(Unavailable):
                parse_ths(text, '1B0016', NOW)
        with self.assertRaises(Unavailable):
            parse_wind(wind(code='000300.SH'), CODE, NOW)

    def test_url_boundary(self):
        for url in ['http://q.10jqka.com.cn/', 'https://q.10jqka.com.cn.attacker.test/',
                    'https://127.0.0.1/', 'https://user:pass@q.10jqka.com.cn/',
                    'https://q.10jqka.com.cn:444/', 'file:///private']:
            with self.subTest(url=url), self.assertRaises(Unavailable):
                safe_url(url)
        self.assertEqual(safe_url(QUOTE_URL), QUOTE_URL)

    def test_frozen_official_response(self):
        text = (Path(__file__).parents[1] / 'reports/live-index-probe/quote0.txt').read_text(encoding='utf-8')
        result = parse_ths(text, '1B0016', NOW)
        self.assertGreater(len(result['points']), 200)
        self.assertEqual(result['as_of'][:10], '2026-10-30')


if __name__ == '__main__':
    unittest.main()
