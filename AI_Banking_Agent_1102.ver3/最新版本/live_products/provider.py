"""Public exchange-traded prices for locally held financial products.

Only exchange-traded funds (``.SH`` / ``.SZ``) have a public quote. Open-end
funds have no secondary market, and bank wealth products have no public market
at all — for those we return a verification link, never a number.

No browser cookies, customer fields, JavaScript execution, paid APIs or TLS
bypass. Selection steps are observable evidence, not private model reasoning.
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from urllib.parse import quote

from live_indices.provider import CN, PublicHTTP, Unavailable, positive, safe_url, validate_time

# d.10jqka.com.cn serves the same JSONP quote bridge for indices (zs_) and
# exchange-traded instruments (hs_). No other host is reachable from here.
PRODUCT_HOSTS = frozenset({'d.10jqka.com.cn'})
QUOTE_ROOT = 'https://d.10jqka.com.cn/v6/time/'

# Code segments, not just suffixes: a six-digit fund code would otherwise be
# served the *stock* registered under that number (000078.OF -> ST海王).
SH_CODES = re.compile(r'5\d{5}')
SZ_CODES = re.compile(r'159\d{3}')

FUND_PAGE = 'https://fund.10jqka.com.cn/'
WEALTH_QUERY = 'https://xinxipilu.chinawealth.com.cn/queryMenu/prodType/prodTypeDetail?prodRegCode='
WEALTH_HOME = 'https://www.chinawealth.com.cn/'
REGISTRATION = re.compile(r'[（(]([A-Za-z0-9]{5,})[)）]')


def product_type(code):
    suffix = code.rsplit('.', 1)[-1].upper()
    return {'.SH': 'exchange_traded', '.SZ': 'exchange_traded',
            '.OF': 'open_end_fund', '.LC': 'bank_wealth'}.get('.' + suffix, 'unknown')


def etf_token(code):
    """Return the six-digit exchange code only for instruments with a public quote.

    ``.OF`` and ``.LC`` never reach a quote URL: see the module docstring.
    """
    body, _, suffix = code.rpartition('.')
    suffix = suffix.upper()
    if suffix == 'SH' and SH_CODES.fullmatch(body):
        return body
    if suffix == 'SZ' and SZ_CODES.fullmatch(body):
        return body
    return None


def registration_code(name):
    """Registration codes appear inside the product name, and only for some issuers."""
    match = REGISTRATION.search(name or '')
    return match.group(1) if match else None


def normalize(text):
    return re.sub(r'[^0-9A-Z一-鿿]', '', str(text or '').upper())


def name_overlap(first, second):
    """Share of bigrams held by the shorter name; None when either is too short."""
    left, right = normalize(first), normalize(second)
    if len(left) < 2 or len(right) < 2:
        return None
    grams = lambda value: {value[i:i + 2] for i in range(len(value) - 1)}
    a, b = grams(left), grams(right)
    return len(a & b) / max(1, min(len(a), len(b)))


def identity_check(local_name, official_name):
    """Reject a quote whose published name does not describe the local product."""
    overlap = name_overlap(local_name, official_name)
    if overlap is None or overlap < 0.5:
        raise Unavailable('返回名称与本地产品不匹配，未作为该产品行情使用')
    return {'local_name': local_name, 'official_name': official_name,
            'name_overlap': round(overlap, 3), 'accepted': True}


def parse_etf_jsonp(text, token, now, local_name):
    """Parse ``quotebridge_v6_time_hs_<token>_last({...})``; data only, never executed."""
    callback = 'quotebridge_v6_time_hs_' + token + '_last'
    match = re.fullmatch(re.escape(callback) + r'\((\{.*\})\);?\s*', text.strip(), re.S)
    if not match:
        raise Unavailable('同花顺响应格式变化或需要登录')
    try:
        quote = json.loads(match[1])['hs_' + token]
        day = datetime.strptime(str(quote['date']), '%Y%m%d').date()
        points, previous = [], None
        for row in quote['data'].strip(';').split(';'):
            fields = row.split(',')
            tick = datetime.strptime(fields[0], '%H%M').time()
            at = datetime.combine(day, tick, CN)
            if previous is not None and at <= previous:
                raise Unavailable('分时记录无序或重复')
            stamp = validate_time(at, now)
            points.append({'date': stamp, 'price': positive(fields[1])})
            previous = at
        if not points:
            raise Unavailable('同花顺未返回当日分时记录')
        identity = identity_check(local_name, quote.get('name', ''))
        price, pre = points[-1]['price'], positive(quote['pre'])
        return {'price': price, 'previous_close': pre, 'as_of': points[-1]['date'],
                'change_1d': price / pre - 1, 'points': points, 'series_kind': 'intraday',
                'price_basis': 'exchange_traded_price', 'quote_kind': 'last_price',
                'currency': 'CNY', 'official_name': str(quote.get('name', ''))[:80],
                'identity': identity, 'freshness': '交易所公开分时最新可用价；非交易时段为最近收盘，可能延迟',
                'stale': False,
                'unavailable_fields': {'nav': '公开分时接口不提供单位净值',
                                       'change_20d': '该公开接口仅提供当日分时'}}
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        if isinstance(exc, Unavailable):
            raise
        raise Unavailable('同花顺缺少匹配代码、有效报价或时间') from None


class ProductProvider:
    def __init__(self, fetch=None, clock=None, ttl=60):
        self.fetch = fetch or PublicHTTP(hosts=PRODUCT_HOSTS, ttl=ttl)
        self.clock = clock or (lambda: datetime.now(CN))
        self.ttl = ttl
        self.lock = threading.Lock()
        self.cached = None

    def quote(self, product, steps):
        """Exchange-traded funds only; everything else is answered without a request."""
        code, name = product['code'], product['name']
        token = etf_token(code)
        if not token:
            raise Unavailable('代码不属于交易所 ETF 段，未查询官方行情，避免与股票代码混淆')
        url = QUOTE_ROOT + 'hs_' + token + '/last.js'
        safe_url(url, PRODUCT_HOSTS)
        step = {'source': '同花顺场内分时', 'search_keywords': '场内ETF ' + code,
                'urls': [url], 'attempted_at': self.clock().isoformat(),
                'method': '公开分时 JSONP；代码段、回调名与名称一致性三重校验'}
        steps.append(step)
        try:
            data = parse_etf_jsonp(self.fetch(url), token, self.clock(), name)
        except (Unavailable, ValueError, KeyError, TypeError, IndexError, RecursionError) as exc:
            step.update(status='unavailable', observation=str(exc)[:200],
                        decision='不展示价格；净值与评分沿用本地快照')
            raise Unavailable(str(exc)) from None
        step.update(status='accepted', identity=data.pop('identity'),
                    observation='代码与名称匹配；价格、前收与报价时间有效',
                    decision='满足价格展示需求；价格不参与评分')
        retrieved = self.fetch.retrieved_at(url) if hasattr(self.fetch, 'retrieved_at') else None
        data.update(code=code, name=name, source='同花顺场内分时', source_url=url,
                    retrieved_at=retrieved or self.clock().isoformat(), sector='')
        return data, url

    def select(self, product):
        code, name, kind = product['code'], product['name'], product_type(product['code'])
        steps = []
        row = {'product_code': code, 'product_name': name, 'product_type': kind,
               'participates_in_scoring': False, 'steps': steps}
        if kind == 'exchange_traded':
            try:
                priced, _ = self.quote(product, steps)
                row.update(status='priced', result_source='同花顺场内分时', final_data=priced)
            except (Unavailable, ValueError, KeyError, TypeError, IndexError, RecursionError):
                row.update(status='unavailable', result_source=None, final_data=None,
                           error='同花顺未提供可核验的该 ETF 场内报价；不补造价格')
            return row
        if kind == 'open_end_fund':
            body = code.rsplit('.', 1)[0]
            steps.append({'source': '同花顺基金官方页面（仅核验，不抓取）',
                          'search_keywords': name + ' ' + code,
                          'urls': [FUND_PAGE + body + '/'], 'attempted_at': self.clock().isoformat(),
                          'method': '只提供人工核验入口；该页净值由脚本渲染，不逆向私有接口',
                          'status': 'not_applicable',
                          'observation': '场外基金无二级市场价格，公开页面不提供服务端净值',
                          'decision': '不展示价格；净值与评分沿用本地快照'})
            row.update(status='not_applicable', result_source=None, final_data=None,
                       verification_url=FUND_PAGE + body + '/',
                       error='场外基金无公开二级市场价格；如需核验请人工打开官方页面')
            return row
        registered = registration_code(name)
        url = WEALTH_QUERY + quote(registered) if registered else WEALTH_HOME
        steps.append({'source': '中国理财网信息披露（仅人工核验）',
                      'search_keywords': name + ' ' + code,
                      'urls': [url], 'attempted_at': self.clock().isoformat(),
                      'method': '按登记编码生成官方查询入口；不自动抓取、不绕过验证码',
                      'status': 'not_applicable',
                      'observation': ('产品名含登记编码 ' + registered) if registered
                                     else '产品名未披露登记编码，需按名称人工检索',
                      'decision': '不展示价格；银行理财无公开交易市场'})
        row.update(status='not_applicable', result_source=None, final_data=None,
                   verification_url=url, registration_code=registered,
                   error='银行理财无公开交易市场；如需核验请人工在中国理财网查询')
        return row

    def resolve(self, products):
        selected = [{'code': p['code'], 'name': p['name']} for p in products]
        key = json.dumps(selected, sort_keys=True, ensure_ascii=False)
        with self.lock:
            if self.cached and self.cached[0] == key and time.monotonic() - self.cached[1] < self.ttl:
                rows = deepcopy(self.cached[2])
                for row in rows:
                    row['cache'] = {'reused': True, 'ttl_seconds': self.ttl,
                                    'note': '复用同一轮完整检查，抓取时间不刷新'}
                return rows
            with ThreadPoolExecutor(max_workers=8) as pool:
                rows = list(pool.map(self.select, selected))
            for row in rows:
                row['cache'] = {'reused': False, 'ttl_seconds': self.ttl}
            self.cached = (key, time.monotonic(), deepcopy(rows))
            return rows
