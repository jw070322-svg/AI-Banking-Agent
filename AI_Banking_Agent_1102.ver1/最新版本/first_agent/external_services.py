"""Read-only public research and local, zero-API-fee model fallback.

No account state, credentials, calendar text, tools or payment APIs go to models.
Public pages are untrusted evidence. Captchas/403s are reported, never bypassed.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit, urljoin
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError
from threading import Lock
from copy import deepcopy
from pathlib import Path
import json, os, re, time

MODEL = 'banking-finance-lora'
MODEL_PORT = 8811
LLAMA = f'http://127.0.0.1:{MODEL_PORT}'
_VERSION_ROOT = Path(__file__).resolve().parents[1]
MODEL_KEY_CANDIDATES = (_VERSION_ROOT/'runtime'/'local-model.key',)
MODEL_KEY = MODEL_KEY_CANDIDATES[0]
PUBLIC_HOSTS = {'www.baidu.com', 'wappass.baidu.com', 'meishi.meituan.com',
                'www.meituan.com', 'www.dianping.com', 'verify.meituan.com'}
LABELS = {'ok':'已返回结果', 'needs_verification':'需要在官方页面验证',
          'unavailable':'连接暂不可用', 'no_results':'未提取到搜索结果',
          'not_checked':'尚未检测', 'model_missing':'本地模型尚未安装',
          'ready':'本地模型可用', 'privacy_blocked':'请改为不含个人资料的通用问题',
          'auth_rejected':'本地模型密钥不匹配，请重新启动本地模型服务'}


def model_key():
    """Return (path, value) for the first usable key file, else (None, '').

    A read failure is treated as "no key" rather than an exception: a locked or
    non-UTF-8 file must not turn a knowledge request into an HTTP 500.
    """
    for path in MODEL_KEY_CANDIDATES:
        try:
            if path.is_file():
                value = path.read_text(encoding='utf-8').strip()
                if value: return path, value
        except (OSError, ValueError):
            continue
    return None, ''


def stamp(): return datetime.now(timezone.utc).isoformat()


def safe_url(value):
    if not isinstance(value, str): return ''
    try:
        u = urlsplit(value)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password: return ''
        if any(ord(c)<32 for c in value): return ''
        return value
    except ValueError: return ''


def public_question(value):
    if not isinstance(value,str) or not 1 <= len(value.strip()) <= 300:
        raise ValueError('请输入 1–300 字的通用问题')
    value=value.strip()
    # Conservative egress boundary, not a claim to comprehensive DLP.
    if re.search(r'\d{7,}|[\w.+-]+@[\w.-]+|https?://|密码|验证码|身份证|手机号|手机号码|住址|银行卡号|api.?key|token|secret|我的|我家|本人|账户|余额|流水|转账|工资|收入|支出|生日|日历',value,re.I):
        raise ValueError('请使用不含账户、身份、联系方式或私人事件的通用问题')
    return value


class RestrictedRedirect(HTTPRedirectHandler):
    def __init__(self, hosts=None):
        self.hosts = PUBLIC_HOSTS if hosts is None else frozenset(hosts)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u=urlsplit(newurl)
        if u.scheme!='https' or u.hostname not in self.hosts or u.port not in (None,443):
            raise URLError('redirect_not_allowed')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


_UNSET = object()


def local_request_headers(url, *, key=_UNSET, hosts=None):
    """Validate `url` and build headers. Returns (is_local, headers).

    Split out of `request()` so the loopback allowlist and the key handling can
    be tested without any socket. Raises ValueError on a disallowed URL.

    `hosts` widens the public allowlist for one call (e.g. an official page).
    None keeps the historical `PUBLIC_HOSTS` behaviour.
    """
    allowed = PUBLIC_HOSTS if hosts is None else frozenset(hosts)
    u=urlsplit(url)
    local=u.scheme=='http' and u.hostname=='127.0.0.1' and u.port==MODEL_PORT and u.path in ('/v1/models','/v1/chat/completions','/lora-adapters')
    if not local and not (u.scheme=='https' and u.hostname in allowed and u.port in (None,443)):
        raise ValueError('不允许的服务地址')
    if u.username or u.password: raise ValueError('不允许 URL 凭据')
    headers={'User-Agent':'AI-Banking-Agent/1.0 (public information research)', 'Accept':'application/json' if local else 'text/html', 'Accept-Encoding':'identity'}
    if local:
        sent = model_key()[1] if key is _UNSET else str(key)
        if sent: headers['Authorization']='Bearer '+sent
    return local, headers


def http_error_result(local, code):
    """Map an HTTP status to a status dict. Local 401/403 is a key mismatch,
    not a public-site verification challenge."""
    if local and code in (401,403):
        return {'status':'auth_rejected','http_status':code}
    return {'status':'needs_verification' if code in (401,403,429) else 'unavailable','http_status':code}


def request(url, payload=None, timeout=8, *, key=_UNSET, hosts=None):
    """`key` overrides the stored key; `hosts` widens the public allowlist for
    this call only. Both default to the historical behaviour."""
    local, headers = local_request_headers(url, key=key, hosts=hosts)
    body=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
    if body is not None: headers['Content-Type']='application/json'
    # 本地请求的跳转规则保持原样（PUBLIC_HOSTS），不因一次外部核验而放宽。
    redirect = RestrictedRedirect(()) if local else RestrictedRedirect(hosts)
    opener=build_opener(ProxyHandler({}), redirect) if local else build_opener(redirect)
    try:
        with opener.open(Request(url,data=body,headers=headers),timeout=timeout) as response:
            raw=response.read(2_000_001)
            if len(raw)>2_000_000: return {'status':'unavailable','reason':'response_too_large'}
            text=raw.decode(response.headers.get_content_charset() or 'utf-8','replace')
            target=urlsplit(response.url)
            title=re.search(r'<title[^>]*>(.*?)</title>',text,re.S|re.I)
            title=title.group(1).strip() if title else ''
            # Check page title/location, not incidental captcha scripts on ordinary pages.
            blocked=target.hostname in ('wappass.baidu.com','verify.meituan.com') or bool(re.search('安全验证|验证中心|访问验证|人机验证',title))
            return {'status':'needs_verification' if blocked else 'ok','http_status':response.status,
                    'body':text if not blocked else '', 'host':target.hostname,'title':title}
    except HTTPError as e:
        return http_error_result(local, e.code)
    except (URLError,TimeoutError,OSError,ValueError):
        return {'status':'unavailable','reason':'network_or_timeout'}


class SearchParser(HTMLParser):
    """Only titled search hits in h3 elements, never navigation or ads invented as data."""
    def __init__(self):
        super().__init__(convert_charrefs=True); self.level=0; self.item=None; self.hits=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='h3': self.level+=1; self.item={'title':'','url':''}
        if self.level and tag=='a': self.item['url']=safe_url(urljoin('https://www.baidu.com',attrs.get('href','')))
    def handle_data(self,data):
        if self.level and self.item: self.item['title']+=data
    def handle_endtag(self,tag):
        if tag=='h3' and self.level:
            self.level-=1
            if self.item and self.item['url'] and self.item['title'].strip():
                self.item['title']=re.sub(r'\s+',' ',self.item['title']).strip()[:200]
                if self.item['url'] not in {x['url'] for x in self.hits}: self.hits.append(self.item)
            self.item=None


class ExternalServices:
    def __init__(self, transport=None):
        self.transport=transport or request; self.lock=Lock(); self.model_lock=Lock(); self.cache={}; self.last={}

    def _record(self,provider,result):
        result={**result,'provider':provider,'retrieved_at':stamp()}
        result['message']=LABELS.get(result['status'],result['status'])
        with self.lock: self.last[provider]={k:v for k,v in result.items() if k not in ('body','items','answer','query','url')}
        return result

    def status(self):
        with self.lock: latest=deepcopy(self.last)
        return {'providers':{p:latest.get(p,{'status':'not_checked','message':LABELS['not_checked']}) for p in ('baidu','llama_cpp')},
                'model':MODEL,'ai_mode':'local_only','paid_api_enabled':False,
                'meituan':{'mode':'official_web_link','merchant_api_connected':False},
                'dianping':{'mode':'official_web_link','merchant_api_connected':False}}

    def links(self,city='',category='餐厅'):
        if not isinstance(city,str) or not re.fullmatch(r'[\u4e00-\u9fffA-Za-z ·-]{0,40}',city): raise ValueError('城市名称无效')
        if category not in ('餐厅','蛋糕','花店'): raise ValueError('仅支持餐厅、蛋糕、花店')
        return {'city':city,'category':category,'query':(city+' '+category).strip(),
                'items':[{'provider':'meituan','title':'打开美团官网','url':'https://www.meituan.com/'},
                         {'provider':'dianping','title':'打开大众点评','url':'https://www.dianping.com/'}],
                'status':'external_search_link','notice':'进入官网后按上方城市和品类搜索；未读取商户价格、评分或库存。'}

    def baidu(self,question):
        query=public_question(question)
        with self.lock: cached=self.cache.get(query)
        if cached and time.monotonic()-cached[0]<120: return {**deepcopy(cached[1]),'cached':True}
        url='https://www.baidu.com/s?'+urlencode({'wd':query})
        response=self.transport(url,timeout=8); items=[]
        if response['status']=='ok':
            parser=SearchParser(); parser.feed(response.get('body','')); items=parser.hits[:5]
            if not items: response['status']='no_results'
        result=self._record('baidu',{'status':response['status'],'http_status':response.get('http_status'),
                  'query':query,'url':url,'items':items,'source_type':'public_search_titles',
                  'notice':'搜索标题是网页线索，未读取或验证正文。','cached':False})
        with self.lock:
            if len(self.cache)>=64: self.cache.pop(next(iter(self.cache)))
            self.cache[query]=(time.monotonic(),deepcopy(result))
        return result

    def model_status(self):
        r=self.transport(LLAMA+'/v1/models',timeout=3)
        status=r['status']
        if status=='ok':
            try:
                models=json.loads(r['body'])['data']
                status='ready' if any(x.get('id')==MODEL for x in models) else 'model_missing'
            except (ValueError,KeyError,TypeError): status='unavailable'
        return self._record('llama_cpp',{'status':status,'model':MODEL,'local_only':True,'api_fee':0})

    def probe(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(self.baidu,'复利的定义'); b=pool.submit(self.model_status)
            return {'baidu':a.result(),'llama_cpp':b.result(),'connections':self.status()}

    def complete(self,system,user,*,max_tokens=400):
        """Local-only completion with the shared output validation.

        No egress filter here beyond the loopback allowlist in `request()`: this
        is a call to our own model on 127.0.0.1. Callers that put user text into
        `user` must filter it themselves (`generate` does).
        """
        if not self.model_lock.acquire(blocking=False):
            return {'status':'unavailable','message':'本地模型正在处理另一个请求，请稍后重试'}
        try:
            payload={'model':MODEL,'stream':False,'temperature':0,'max_tokens':max_tokens,
                     'messages':[{'role':'system','content':system},{'role':'user','content':user}]}
            r=self.transport(LLAMA+'/v1/chat/completions',payload,timeout=45)
            if r['status']!='ok': return self._record('llama_cpp',{'status':r['status'],'answer':''})
            try:
                choice=json.loads(r['body'])['choices'][0]; answer=choice['message']['content'].strip()
                if choice.get('finish_reason')!='stop' or not answer or len(answer)>4000 or choice['message'].get('tool_calls'): raise ValueError()
                if '<think' in answer or '</think>' in answer: raise ValueError()
            except (ValueError,KeyError,TypeError,AttributeError,IndexError):
                return self._record('llama_cpp',{'status':'unavailable','reason':'invalid_model_output','answer':''})
            return self._record('llama_cpp',{'status':'ok','answer':answer,'model':MODEL,'local_only':True,'api_fee':0})
        finally: self.model_lock.release()

    def generate(self,question):
        query=public_question(question)
        return self.complete('你是中文金融知识助理。只解释通用概念，用不超过200字的简洁中文。你没有实时行情、商户信息或客户账户数据，不能编造价格、来源、最新利率或声称执行操作。不得输出内部推理。不调用工具，不给具体买卖建议。',query)

    def fallback(self,question,local,public_search_approved=False):
        try: query=public_question(question)
        except ValueError:
            return {**local,'fallback_status':'privacy_blocked','answer':LABELS['privacy_blocked'],'fallback_steps':[], 'external_data_sent':False}
        # Knowledge questions never leave the bank automatically. A separate,
        # explicit search action is required for each public Baidu query.
        search=self.baidu(query) if public_search_approved is True else None
        steps=[{'provider':'local_rag','status':local.get('status')},{'provider':'baidu','status':search['status'] if search else 'not_requested'}]
        # Never use generated current rates, merchant prices or investment decisions as facts.
        current=bool(re.search(r'今天|今日|当前|最新|现在|今年|近期|本周|本月|价格|多少钱|利率|收益率|买哪|卖出|买入|推荐.*产品|202\d',query))
        if current:
            model={'status':'not_used'}
            answer='这需要最新且可核验的数据。当前只有搜索线索或检索受限，未用模型记忆编造数值；请打开来源核对或导入正式数据。'
        else:
            model=self.generate(query)
            answer='本地 AI 已响应，但没有可核验的正文来源，暂不展示未经核实的解释。可主动选择百度搜索或补充正式资料。' if model.get('answer') else '知识库没有足够依据，本地模型暂不可用。可主动选择百度搜索或补充资料。'
        steps.append({'provider':'llama_cpp','status':model['status']})
        return {**local,'status':'needs_evidence','model_response_received':bool(model.get('answer')),
                'answer':answer,'citations':[], 'evidence':[], 'search_results':search.get('items',[]) if search else [],
                'search_url':search.get('url','') if search else '','search_status':search.get('message','') if search else '未主动发起公开搜索','fallback_steps':steps,
                'generation_mode':'llama_cpp' if model.get('answer') else 'none','model':MODEL,'public_query':query,
                'warnings':['本地小模型只作通用解释，不作为银行条款、实时市场数据或交易依据。'],
                'external_data_sent':bool(search),'sent_fields':['public_question'] if search else [],'api_fee':0,'retrieved_at':stamp()}
