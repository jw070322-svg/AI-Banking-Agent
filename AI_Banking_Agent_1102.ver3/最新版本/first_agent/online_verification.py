"""Opt-in verification of a glossary term against its declared official source.

Why this exists
---------------
The local answer path can end with "本地资料不足". Until now the only follow-up
was a Baidu link. This module adds the honest alternative: the local glossary
(`knowledge/finance_glossary.json`) already records, for every term, the
official page its definition came from. With explicit per-request consent we
fetch that page, pull the passages that actually mention the term, and return
them as citations with publisher, date, fetch time and a content hash.

What it is not
--------------
- Not a search engine. Only the source a term already declares is fetched.
- Not automatic. Nothing leaves the machine unless the caller passes
  `online_verify=True` for that one request.
- Not a correctness oracle. It proves the official page says this; it does not
  prove the local answer is semantically right, nor that it suits a customer.
- The model never decides what the evidence is. A one-sentence rewrite may be
  produced, always labelled and always placed after the quoted original.

Measured reality (2026-10-31, 1030.ver4):
- 52 terms point at `www.csrc.gov.cn/*.shtml`. Those pages are fetchable and the
  body text is clean.
- 49 terms point at PDFs under `guiyang.pbc.gov.cn`. The column index page
  answers 200 but renders its article list client-side, so no server-side match
  exists. Those terms return `source_unparseable` with the PDF link rather than
  a fabricated excerpt.
- `investor.gov` (33 terms) is outside the approved allowlist on purpose.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = VERSION_ROOT / 'runtime' / 'online-evidence'

# 只允许这四家监管/官方站点（术语表实际用到 guiyang.pbc.gov.cn 子域）。
EVIDENCE_HOSTS = frozenset({
    'www.csrc.gov.cn', 'www.gov.cn', 'www.pbc.gov.cn',
    'www.nfra.gov.cn', 'guiyang.pbc.gov.cn',
})

# 仅作跳转，永不抓取、永不引用。
AI_LINK = {
    'deepseek': 'https://chat.deepseek.com/',
    'kimi': 'https://kimi.moonshot.cn/',
    'yiyan': 'https://yiyan.baidu.com/',
    'tongyi': 'https://tongyi.aliyun.com/',
}

CN = timezone(timedelta(hours=8))
MAX_PASSAGES = 3
MAX_PAGE_BYTES = 900_000
MIN_BLOCK = 20
MAX_BLOCK = 600
REWRITE_LIMIT = 120

REWRITE_LABEL = '模型改写（非引用原文）'
REWRITE_SYSTEM = '你是中文金融资料助理。只做原文概括，不补充任何原文没有的信息。'
REWRITE_PROMPT = ('只根据给出的官方原文，用一句不超过80字的中文概括其要点。'
                  '不要列举、不要编号、不要分点。不得添加原文没有的数字、日期、机构名或结论。'
                  '只输出这一句话。')


def _now() -> str:
    return datetime.now(CN).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class VisibleText(HTMLParser):
    """Collect visible block text plus the bits of provenance the page carries."""

    SKIP = {'script', 'style', 'noscript', 'svg'}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.buffer: list[str] = []
        self.blocks: list[str] = []
        self.title = ''
        self.meta: dict[str, str] = {}
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self._in_title = True
        elif tag == 'meta':
            values = dict(attrs)
            name = (values.get('name') or '').strip()
            content = (values.get('content') or '').strip()
            if name and content:
                self.meta[name] = content
        elif tag in self.SKIP:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
        elif tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in ('p', 'div', 'li', 'td', 'h1', 'h2', 'h3', 'h4', 'br'):
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self.skip:
            return
        text = data.strip()
        if text:
            self.buffer.append(text)

    def _flush(self):
        if not self.buffer:
            return
        text = re.sub(r'\s+', ' ', ' '.join(self.buffer)).strip()
        self.buffer = []
        if MIN_BLOCK <= len(text) <= MAX_BLOCK:
            self.blocks.append(text)

    def close(self):
        super().close()
        self._flush()


def _entries() -> list[dict]:
    from first_agent import finance_lexicon

    return list(finance_lexicon.entries())


def _normalize(value: str) -> str:
    from first_agent import finance_lexicon

    return finance_lexicon.normalize(value)


def declared_source(question: str, *, entries: Iterable[Mapping] | None = None) -> dict | None:
    """Find the glossary term the question is about, and the source it declares.

    Deliberately a *loose* match: `finance_lexicon.answer()` refuses anything
    with leftover words, which is exactly the case where verification is
    wanted (the corpus had nothing). Here we only need "which term is this
    question about", so a contained term/alias is enough.
    """
    if not isinstance(question, str) or not question.strip():
        return None
    text = _normalize(question)
    best: list[tuple[int, dict]] = []
    for item in (list(entries) if entries is not None else _entries()):
        for alias in [item['term'], *item.get('aliases', [])]:
            key = _normalize(alias)
            if len(key) >= 2 and key in text:
                best.append((len(key), item))
                break
    if not best:
        return None
    best.sort(key=lambda pair: -pair[0])
    chosen = best[0][1]
    return {'term': chosen['term'], 'source_uri': chosen['source_uri'],
            'source_title': chosen.get('source_title', ''), 'definition': chosen.get('definition', ''),
            'candidates': [item['term'] for _, item in best[:2]]}


def fetch_page(url: str, *, transport=None) -> dict:
    """Fetch one allowlisted page. Returns a dict, never raises for network issues."""
    from first_agent.external_services import request as default_request
    from urllib.parse import urlsplit

    # 白名单在这里再挡一次：即使注入了别的 transport，也不能去非官方站点。
    if urlsplit(str(url)).hostname not in EVIDENCE_HOSTS:
        return {'status': 'blocked', 'reason': 'host_not_allowlisted', 'url': url}
    call = transport or default_request
    try:
        result = call(url, timeout=12, hosts=EVIDENCE_HOSTS)
    except ValueError as exc:                      # host not allowlisted, etc.
        return {'status': 'blocked', 'reason': str(exc), 'url': url}
    except Exception as exc:
        return {'status': 'unavailable', 'reason': f'{type(exc).__name__}', 'url': url}
    if result.get('status') != 'ok':
        return {'status': 'unavailable', 'reason': result.get('status'),
                'http_status': result.get('http_status'), 'url': url}
    body = result.get('body') or ''
    if len(body) > MAX_PAGE_BYTES:
        return {'status': 'unavailable', 'reason': 'response_too_large', 'url': url}
    parser = VisibleText()
    parser.feed(body)
    parser.close()
    return {'status': 'ok', 'url': url, 'http_status': result.get('http_status'),
            'content_sha256': _sha(body), 'title': parser.title.strip(),
            'meta': parser.meta, 'blocks': parser.blocks, 'fetched_at': _now()}


def score_block(block: str, term: str) -> int:
    """Simple, explainable ranking: term hits first, then shorter blocks."""
    hits = block.count(term)
    return hits * 100 + (60 - min(len(block), 60))


def select_passages(blocks: Iterable[str], term: str, *, limit: int = MAX_PASSAGES) -> list[dict]:
    scored = [(score_block(block, term), index, block)
              for index, block in enumerate(blocks) if term in block]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [{'text': block, 'block_index': index, 'score': score}
            for score, index, block in scored[:limit]]


def _publisher(page: Mapping) -> str:
    meta = page.get('meta') or {}
    return str(meta.get('ContentSource') or meta.get('contentSource') or '').strip()


def _published_at(page: Mapping) -> str:
    """Prefer the article's own date line; the meta PubDate is often the
    re-publication timestamp of the current site, which misleads."""
    for block in page.get('blocks') or []:
        match = re.search(r'日期[：:]\s*(\d{4}-\d{2}-\d{2})', block)
        if match:
            return match.group(1)
    meta = page.get('meta') or {}
    raw = str(meta.get('PubDate') or meta.get('pubDate') or '').strip()
    match = re.match(r'(\d{4}-\d{2}-\d{2})', raw)
    return match.group(1) if match else raw


def _title(page: Mapping) -> str:
    meta = page.get('meta') or {}
    return str(meta.get('ArticleTitle') or page.get('title') or '').strip()


def _freeze(page: Mapping, excerpt: str) -> str:
    """Write the excerpt snapshot for audit. Returns the sha256 of the page."""
    digest = str(page.get('content_sha256') or '')
    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        target = EVIDENCE_DIR / f'{digest[:16]}.json'
        if not target.exists():
            target.write_text(json.dumps({
                'url': page.get('url'), 'fetched_at': page.get('fetched_at'),
                'http_status': page.get('http_status'), 'title': _title(page),
                'publisher': _publisher(page), 'published_at': _published_at(page),
                'content_sha256': digest, 'excerpt': excerpt,
                'block_count': len(page.get('blocks') or []),
                'note': '官方公开页面摘录；不含客户数据，不含提问原文',
            }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except OSError:
        pass
    return digest


def _numbers(text: str) -> set[str]:
    return set(re.findall(r'\d+(?:\.\d+)?', text))


def safe_rewrite(text: str, excerpt: str) -> dict:
    """Accept a model sentence only if it adds no fact the excerpt lacks.

    "One sentence" is enforced mechanically: a small model tends to answer with
    a list, so we keep the first sentence and drop the rest. If even that is too
    long the rewrite is dropped entirely rather than truncated mid-thought.
    """
    raw = (text or '').strip()
    if not raw:
        return {'status': 'rejected', 'reason': 'empty'}
    first = next((part.strip() for part in re.split(r'(?<=[。！？!?])', raw) if part.strip()), '')
    sentence = first or raw
    if len(sentence) > REWRITE_LIMIT:
        return {'status': 'rejected', 'reason': 'too_long'}
    if re.search(r'https?://|<think|</think', sentence):
        return {'status': 'rejected', 'reason': 'unsafe_content'}
    if not _numbers(sentence) <= _numbers(excerpt):
        return {'status': 'rejected', 'reason': 'invented_numbers'}
    if re.match(r'(根据规定|据悉|据了解|研究表明)', sentence):
        return {'status': 'rejected', 'reason': 'unsupported_attribution'}
    return {'status': 'ok', 'text': sentence, 'label': REWRITE_LABEL}


def _rewrite(excerpt: str, *, model=None) -> dict:
    """One-sentence restatement. Dropped entirely when the model is unusable.

    Uses `complete()` rather than `generate()`: the excerpt is page text, not a
    user question, so it must not go through the public-question filter (which
    would reject most excerpts for length alone). Still a loopback-only call.
    """
    from first_agent.external_services import ExternalServices

    service = model if model is not None else ExternalServices()
    try:
        # 只喂第一句：把整段（最多 600 字）塞给小模型时，它会照抄或列点，
        # 必然超出"一句"。短输入才拿得到短输出。
        seed = re.split(r'(?<=[。！？；!?;])', excerpt.strip())[0][:110]
        result = service.complete(REWRITE_SYSTEM, f'{REWRITE_PROMPT}\n\n官方原文：{seed}',
                                  max_tokens=96)
    except Exception:
        return {'status': 'unavailable', 'label': REWRITE_LABEL}
    if not result.get('answer'):
        return {'status': 'unavailable', 'label': REWRITE_LABEL}
    return safe_rewrite(result['answer'], excerpt)


def verify(question: str, *, transport=None, model=None,
           entries: Iterable[Mapping] | None = None) -> dict:
    """Fetch the declared official source and return verifiable passages."""
    base = {'status': 'no_source', 'term': '', 'sources': [], 'citations': [],
            'rewrite': {'status': 'unavailable', 'label': REWRITE_LABEL},
            'ai_links': AI_LINK, 'steps': []}

    try:
        from first_agent.external_services import public_question
        public_question(question)
    except ValueError as exc:
        return {**base, 'status': 'blocked', 'detail': str(exc)}

    source = declared_source(question, entries=entries)
    if source is None:
        return {**base, 'detail': '知识库里没有与该问题对应的已声明出处'}

    term, uri = source['term'], source['source_uri']
    steps: list[dict] = []
    base['term'] = term

    if uri.lower().endswith('.pdf'):
        # 标准库无法抽取 PDF 正文；按约定先尝试栏目索引找 HTML 替代页。
        # 已实测：pbc 栏目索引返回 200 但文章列表由客户端渲染，这里大概率找不到。
        for index_url in _column_indexes(uri):
            page = fetch_page(index_url, transport=transport)
            steps.append({'provider': 'official_web', 'url': index_url,
                          'status': f"index:{page.get('status')}"})
            if page.get('status') == 'ok':
                passages = select_passages(page.get('blocks') or [], term, limit=1)
                if passages:
                    # 索引页本身正文里就有该术语的段落，可直接引用。
                    return _verified(base, steps, page, passages, term)
        return {**base, 'status': 'source_unparseable', 'steps': steps,
                'sources': [{'url': uri, 'kind': 'pdf', 'source_uri': uri}],
                'detail': '该术语的官方出处是 PDF，且栏目索引页没有服务端可解析的文章列表'}

    page = fetch_page(uri, transport=transport)
    steps.append({'provider': 'official_web', 'url': uri, 'status': page.get('status')})
    if page.get('status') != 'ok':
        return {**base, 'status': page.get('status', 'unavailable'), 'steps': steps,
                'detail': page.get('reason') or ''}

    passages = select_passages(page.get('blocks') or [], term)
    if not passages:
        return {**base, 'status': 'partial', 'steps': steps,
                'sources': [{'url': uri, 'title': _title(page), 'publisher': _publisher(page),
                             'published_at': _published_at(page), 'fetched_at': page.get('fetched_at'),
                             'content_sha256': page.get('content_sha256'), 'http_status': page.get('http_status')}],
                'detail': f'官方页面已取回，但未找到包含「{term}」的段落'}

    return _verified(base, steps, page, passages, term, model=model)


def _column_indexes(pdf_url: str) -> list[str]:
    """Candidate HTML listing pages around a PDF (nearest directory first)."""
    match = re.fullmatch(r'(?P<base>.+)/(?P<dir>\d+)/[^/]+\.pdf', pdf_url)
    if not match:
        return []
    base = match.group('base')
    return [f'{base}/{match.group("dir")}/index.html', f'{base}/index.html']


def _verified(base, steps, page, passages, term, *, model=None) -> dict:
    excerpt = passages[0]['text']
    digest = str(page.get('content_sha256') or _sha(excerpt))
    _freeze(page, excerpt)
    uri = page.get('url')
    citations = []
    for number, passage in enumerate(passages, 1):
        citations.append({
            'citation_id': f'S{number}',
            'document_id': f'web-{digest[:8]}',
            'title': _title(page) or term,
            'section': '',
            'source_uri': uri,
            'excerpt': passage['text'],
            'published_at': _published_at(page),
            'publisher': _publisher(page),
            'fetched_at': page.get('fetched_at'),
            'document_sha256': digest,
            'kind': 'official_web',
        })
    return {**base,
            'status': 'verified',
            'steps': steps,
            'sources': [{'url': uri, 'title': _title(page), 'publisher': _publisher(page),
                         'published_at': _published_at(page), 'fetched_at': page.get('fetched_at'),
                         'content_sha256': digest, 'http_status': page.get('http_status')}],
            'citations': citations,
            'rewrite': _rewrite(excerpt, model=model),
            'answer': '以下为官方原文摘录，未经改写；请以原文为准。',
            'detail': f"在{_publisher(page) or '官方页面'}中命中「{term}」"}
