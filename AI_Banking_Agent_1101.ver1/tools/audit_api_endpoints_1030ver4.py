"""Static audit of the project's HTTP surface: routes vs. documentation.

The project has no web framework and no `/api/v1`-style versioning; routes are
plain string literals matched inside stdlib `http.server` handlers. So the only
useful definition of "up to date" is: every route the code actually serves is
described in the contract, and every route the contract claims really exists.

This script compares those two sets and writes the diff. It changes nothing.

Run: python tools/audit_api_endpoints_1030ver4.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'reports/api-endpoints-1030ver4.json'

# 代码里真正挂路由的地方（order matters only for readability）。
ROUTE_SOURCES = (
    'first_agent/server.py',
    'review_additions/runtime.py',
    'relay_additions/runtime.py',
    'ui_fix/server.py',
    'live_indices/runtime.py',
    'modules/环境生成agent/scenario_server.py',
)

CONTRACTS = ('API-CONTRACT.md', 'API-EXPERIENCE-1029.md')

ROUTE_PATTERN = re.compile(r"['\"]((?:/api|/review|/relay|/planning-market)[^'\"\s]*)['\"]")
DOC_PATTERN = re.compile(r"`?(/(?:api|review|relay)/[A-Za-z0-9_./{}:<>-]+)`?")

# 文档里用 {} / :id 写参数，代码里用 <...> 或正则组；归一化成同一形状再比。
NORMALISERS = (
    (re.compile(r'\{[^/}]*\}?'), '{}'),
    (re.compile(r'<[^/>]*>'), '{}'),
    (re.compile(r'\([^/]*?\)'), '{}'),
    (re.compile(r':[A-Za-z_][A-Za-z0-9_]*'), '{}'),
)

# 静态资源与 JS 入口不是 API；单独列出，不算“文档缺失”。
ASSET_PREFIXES = ('/planning-market.js', '/review/experience.js',
                  '/review/experience.css', '/review/source-links.js')


def normalise(path: str) -> str:
    for pattern, replacement in NORMALISERS:
        path = pattern.sub(replacement, path)
    return path.rstrip('/') or '/'


def covered_by(path: str, others) -> bool:
    """前缀路由也算覆盖：代码用 startswith 匹配，文档写完整路径。"""
    for other in others:
        if path == other:
            return True
        if other.startswith(path.rstrip('/') + '/'):
            return True
        if path.startswith(other.rstrip('/') + '/'):
            return True
    return False


def implemented() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for rel in ROUTE_SOURCES:
        path = ROOT / rel
        if not path.is_file():
            continue
        for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for literal in ROUTE_PATTERN.findall(line):
                key = normalise(literal)
                found.setdefault(key, []).append(f'{rel}:{line_no}')
    return found


def documented() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for rel in CONTRACTS:
        path = ROOT / rel
        if not path.is_file():
            continue
        for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for literal in DOC_PATTERN.findall(line):
                key = normalise(literal)
                found.setdefault(key, []).append(f'{rel}:{line_no}')
    return found


def main() -> int:
    code, docs = implemented(), documented()
    assets = {p: ev for p, ev in code.items() if p.startswith(ASSET_PREFIXES)}
    code_api = {p: ev for p, ev in code.items() if p not in assets}
    undocumented = sorted(p for p in code_api if not covered_by(p, docs))
    unimplemented = sorted(p for p in docs if not covered_by(p, code_api))
    report = {
        'generated_by': 'tools/audit_api_endpoints_1030ver4.py',
        'generated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'scope': '静态字符串级核对；不是运行时路由分发表，也不校验参数语义',
        'framework': 'stdlib http.server（无 FastAPI/Flask/Starlette，故无框架版本迁移）',
        'versions_in_paths': {
            'internal': '无 /api/v1、/api/v2、api_version；版本由 APP_VERSION 与会话 cookie 名表达',
            'third_party': ['/v6/ 同花顺分时', '/v3/ Google Calendar',
                            '/v1/ 本地 llama.cpp', 'Wind ?v=1 与 detail.js?v=20240409'],
        },
        'summary': {
            'routes_in_code': len(code),
            'routes_in_code_api': len(code_api),
            'static_assets_excluded': len(assets),
            'routes_in_docs': len(docs),
            'in_code_not_in_docs': len(undocumented),
            'in_docs_not_in_code': len(unimplemented),
        },
        'in_code_not_in_docs': [{'path': p, 'evidence': code_api[p]} for p in undocumented],
        'in_docs_not_in_code': [{'path': p, 'evidence': docs[p]} for p in unimplemented],
        'static_assets': [{'path': p, 'evidence': ev} for p, ev in sorted(assets.items())],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False))
    print('in_code_not_in_docs:', undocumented)
    print('in_docs_not_in_code:', unimplemented)
    return 0


if __name__ == '__main__':
    sys.exit(main())
