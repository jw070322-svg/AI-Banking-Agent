"""Public, dated quotes: THS -> Wind official -> bundled Wind, per index.

No browser cookies, customer fields, JavaScript execution, paid APIs or TLS bypass.
Selection steps are observable evidence, not private model reasoning.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.client import HTTPException
import json
import math
import re
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

CN = timezone(timedelta(hours=8))
THS = 'https://q.10jqka.com.cn/zs/'
WIND = 'https://www.wind.com.cn/portal/en/WindIndex/detail.html?id=2&v=1'
WIND_SCRIPT = 'https://www.wind.com.cn/portal/en/WindIndex/js/detail.js?v=20240409'
HOSTS = {'q.10jqka.com.cn', 'd.10jqka.com.cn', 'www.wind.com.cn', 'index_api.wind.com.cn'}
DEFAULTS = [
    ('000016.SH', '上证50指数'), ('000300.SH', '沪深300指数'),
    ('000852.SH', '中证1000指数'), ('000928.SH', '中证全指能源指数'),
    ('000932.SH', '中证主要消费指数'), ('000992.SH', '中证全指金融地产指数'),
    ('399905.SZ', '中证500指数'), ('399989.SZ', '中证医疗指数'),
    ('931186.CSI', '中证科技50策略指数')]


class Unavailable(ValueError):
    pass


def safe_url(url, hosts=None):
    # hosts 默认取模块级 HOSTS；其他模块可传入自己的白名单，指数行为保持不变。
    allowed = HOSTS if hosts is None else hosts
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.port not in (None, 443)
            or parsed.username or parsed.password):
        raise Unavailable('非允许的官方 HTTPS 地址，已阻止')
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # An interface change must be reviewed; never follow an arbitrary redirect.
        raise Unavailable('官网发生重定向，待核验新接口')


class PublicHTTP:
    def __init__(self, timeout=4, ttl=60, hosts=None):
        self.timeout, self.ttl = timeout, ttl
        self.hosts = HOSTS if hosts is None else frozenset(hosts)
        self.cache = {}
        self.locks = {}
        self.guard = threading.Lock()

    def __call__(self, url):
        safe_url(url, self.hosts)
        with self.guard:
            lock = self.locks.setdefault(url, threading.Lock())
        with lock:
            old = self.cache.get(url)
            if old and time.monotonic() - old[0] < self.ttl:
                if isinstance(old[1], Exception):
                    raise Unavailable(str(old[1]))
                return old[1]
            try:
                opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
                req = Request(url, headers={'User-Agent': 'Mozilla/5.0 AI-Banking-IndexReader/1.0',
                                            'Accept': 'application/json,text/html,*/*'})
                started = time.monotonic()
                with opener.open(req, timeout=self.timeout) as response:
                    chunks, length = [], 0
                    while True:
                        block = response.read(65536)
                        if not block:
                            break
                        length += len(block)
                        if length > 1_500_000 or time.monotonic() - started > 8:
                            raise Unavailable('官方响应超过大小或时间限制')
                        chunks.append(block)
                    raw = b''.join(chunks)
                    charset = response.headers.get_content_charset()
                try:
                    text = raw.decode(charset or 'utf-8')
                except (UnicodeError, LookupError):
                    text = raw.decode('gb18030', errors='replace')
            except HTTPError as exc:
                error = Unavailable('官网 HTTP ' + str(exc.code) + '，不绕过登录或反爬限制')
                self.cache[url] = (time.monotonic(), error)
                raise error from None
            except (URLError, OSError, HTTPException, Unavailable) as exc:
                reason = getattr(exc, 'reason', exc)
                if isinstance(reason, ssl.SSLCertVerificationError):
                    message = '官网 TLS 证书校验失败；未关闭证书验证'
                elif isinstance(exc, Unavailable):
                    message = str(exc)
                else:
                    message = '官网连接失败或超时（' + type(reason).__name__ + '）'
                error = Unavailable(message)
                self.cache[url] = (time.monotonic(), error)
                raise error from None
            self.cache[url] = (time.monotonic(), text, datetime.now(CN).isoformat())
            return text

    def retrieved_at(self, url):
        cached = self.cache.get(url)
        return cached[2] if cached and len(cached) > 2 else None


def positive(value):
    if isinstance(value, bool):
        raise Unavailable('数值类型错误')
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise Unavailable('指数数值缺失') from None
    if not math.isfinite(number) or number <= 0:
        raise Unavailable('指数数值不是有效正数')
    return number


def validate_time(stamp, now):
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=CN)
    if stamp > now + timedelta(minutes=5):
        raise Unavailable('报价时间在未来，未作为实时数据使用')
    # Ten calendar days accommodates long exchange holidays. Never calls this guaranteed real-time.
    if now - stamp > timedelta(days=10):
        raise Unavailable('官网报价超过10个自然日，已过时')
    return stamp.isoformat()


def ths_token(code):
    if re.fullmatch(r'000\d{3}\.SH', code):
        return '1B' + code[2:6]
    if re.fullmatch(r'399\d{3}\.SZ', code):
        return code[:6]
    return None


def parse_ths(text, token, now):
    # JSONP is data only: no eval/exec and an exact callback and instrument key.
    callback = 'quotebridge_v6_time_zs_' + token + '_last'
    match = re.fullmatch(re.escape(callback) + r'\((\{.*\})\);?\s*', text.strip(), re.S)
    if not match:
        raise Unavailable('同花顺响应格式变化或需要登录')
    try:
        quote = json.loads(match[1])['zs_' + token]
        day = datetime.strptime(str(quote['date']), '%Y%m%d').date()
        points = []
        previous = None
        for row in quote['data'].strip(';').split(';'):
            fields = row.split(',')
            tick = datetime.strptime(fields[0], '%H%M').time()
            at = datetime.combine(day, tick, CN)
            if previous is not None and at <= previous:
                raise Unavailable('分时记录无序或重复')
            stamp = validate_time(at, now)
            points.append({'date': stamp, 'close': positive(fields[1])})
            previous = at
        close = points[-1]['close']
        pre = positive(quote['pre'])
        return {'close': close, 'previous_close': pre, 'as_of': points[-1]['date'],
                'change_1d': close / pre - 1, 'change_20d': None,
                'points': points, 'series_kind': 'intraday',
                'official_name': str(quote.get('name', ''))[:80],
                'freshness': '官网最新可用分时；可能延迟', 'stale': False,
                'unavailable_fields': {'change_20d': '此公开接口仅提供当日分时，不混入本地20日涨跌幅'}}
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        if isinstance(exc, Unavailable):
            raise
        raise Unavailable('同花顺缺少匹配代码、有效报价或时间') from None


class WindEmbedded(HTMLParser):
    """Only recognized, explicit JSON quote records; arbitrary page numbers are not quotes."""
    def __init__(self):
        super().__init__()
        self.collect = False
        self.blocks = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.collect = tag == 'script' and a.get('type') == 'application/json'
    def handle_data(self, data):
        if self.collect:
            self.blocks.append(data)
    def handle_endtag(self, tag):
        if tag == 'script':
            self.collect = False


def parse_wind(text, code, now):
    parser = WindEmbedded()
    parser.feed(text)
    blocks = [text] if text.lstrip().startswith(('{', '[')) else parser.blocks
    def records(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from records(child)
        elif isinstance(value, list):
            for child in value:
                yield from records(child)
    for block in blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for row in records(data):
            if row.get('code') != code:
                continue
            try:
                at = validate_time(datetime.fromisoformat(row['as_of']), now)
                close, pre = positive(row['close']), positive(row['previous_close'])
            except (KeyError, ValueError, TypeError):
                continue
            return {'close': close, 'previous_close': pre, 'as_of': at,
                    'change_1d': close / pre - 1, 'change_20d': None, 'points': [],
                    'series_kind': 'quote', 'stale': False, 'freshness': 'Wind官网最新可用报价；可能延迟',
                    'unavailable_fields': {'change_20d': '官网未提供可核验20日序列'}}
    raise Unavailable('Wind公开页面没有该完整指数代码的带日期报价；不把其他Wind指数当成目标指数')


class IndexProvider:
    def __init__(self, fetch=None, clock=None, ttl=60):
        self.fetch = fetch or PublicHTTP(ttl=ttl)
        self.clock = clock or (lambda: datetime.now(CN))
        self.ttl = ttl
        self.lock = threading.Lock()
        self.cached = None

    def ths(self, code, evidence):
        directory = self.fetch(THS)
        token = ths_token(code)
        if not token or not re.search(r'/zs/detail/code/' + re.escape(token) + r'/', directory):
            raise Unavailable('同花顺官方指数目录未找到目标代码的行情入口')
        url = 'https://d.10jqka.com.cn/v6/time/zs_' + token + '/last.js'
        evidence.append(url)
        return parse_ths(self.fetch(url), token, self.clock()), url

    def wind(self, code, evidence):
        page = self.fetch(WIND)
        try:
            return parse_wind(page, code, self.clock()), WIND
        except Unavailable:
            pass
        evidence.append(WIND_SCRIPT)
        script = self.fetch(WIND_SCRIPT)
        # Follow only the iframe selected by id=2 in the supplied official page.
        match = re.search(r'case\s*[\'"]2[\'"]\s*:\s*\w+\s*=\s*[\'"](https://index_api\.wind\.com\.cn/[^\'\"]+)', script)
        if not match:
            raise Unavailable('Wind官方脚本未提供可核验的目标页面地址；接口变化需人工核验')
        url = safe_url(match[1])
        evidence.append(url)
        return parse_wind(self.fetch(url), code, self.clock()), url

    def select(self, spec, local):
        code, name = spec
        steps = []
        result = {'index_name': name, 'index_code': code, 'steps': steps}
        for label, root, method in [('同花顺', THS, self.ths), ('Wind官网', WIND, self.wind)]:
            urls = [root]
            step = {'source': label, 'search_keywords': name + ' ' + code, 'urls': urls,
                    'attempted_at': self.clock().isoformat(), 'method': '官方目录/页面按指数代码检索，读取公开数据'}
            steps.append(step)
            try:
                quote, url = method(code, urls)
                step.update(status='accepted', observation='代码匹配；数值、报价时间有效',
                            decision='满足当前报价需求，停止后续来源尝试')
                fetched_at = self.fetch.retrieved_at(url) if hasattr(self.fetch, 'retrieved_at') else None
                quote.update(code=code, name=name, source=label, source_url=url,
                             retrieved_at=fetched_at or self.clock().isoformat(), sector=(local or {}).get('sector', ''))
                result.update(result_source=label, final_data=quote)
                return result
            except (Unavailable, ValueError, KeyError, TypeError, RecursionError) as exc:
                step.update(status='unavailable', observation=str(exc)[:200],
                            decision='继续尝试Wind官网' if label == '同花顺' else '两种官网均未满足需求，允许读取本地Wind备选')
        quote = deepcopy(local) if local else None
        reason = None
        try:
            if quote:
                positive(quote['close'])
                datetime.fromisoformat(quote['as_of'])
                quote.update(source='本地wind数据表格', source_url=None, series_kind='daily',
                             retrieved_at=self.clock().isoformat(), freshness='本地历史快照，非实时',
                             stale=(self.clock().date() - datetime.fromisoformat(quote['as_of']).date()).days > 10)
            else:
                reason = '本地表格也没有该指数的有效观测数据'
        except (ValueError, TypeError, KeyError):
            quote = None
            reason = '本地指数数据不完整，未伪造数值'
        steps.append({'source': '本地wind数据表格', 'status': 'accepted' if quote else 'unavailable',
                      'observation': '读取原有Wind指数快照；保留真实观察日' if quote else reason,
                      'decision': '以历史备选展示，明确非实时' if quote else '展示不可用，final_data=null'})
        result.update(result_source='本地wind数据表格', final_data=quote)
        if reason:
            result['error'] = reason
        return result

    def resolve(self, local_cards, specs=None):
        local = {row['code']: row for row in local_cards}
        selected = list(specs) if specs is not None else list((dict(DEFAULTS) | {
            r['code']: r['name'] for r in local_cards}).items())
        # This key keeps simulated-date/local-snapshot changes from reusing another context.
        key = json.dumps([selected, local_cards], sort_keys=True, ensure_ascii=False)
        with self.lock:
            if self.cached and self.cached[0] == key and time.monotonic() - self.cached[1] < self.ttl:
                rows = deepcopy(self.cached[2])
                for row in rows:
                    row['cache'] = {'reused': True, 'ttl_seconds': self.ttl,
                                    'note': '复用同一轮完整来源检查，抓取时间不刷新'}
                return rows
            with ThreadPoolExecutor(max_workers=6) as pool:
                rows = list(pool.map(lambda spec: self.select(spec, local.get(spec[0])), selected))
            for row in rows:
                row['cache'] = {'reused': False, 'ttl_seconds': self.ttl}
            self.cached = (key, time.monotonic(), deepcopy(rows))
            return rows
