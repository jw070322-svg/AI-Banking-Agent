#!/usr/bin/env python3
"""Build the relocation ledger for files moved out of the version root.

旧基线（reports/1029-preservation-baseline.json 等）记录的是根目录路径。启动器
归档把若干历史入口移入 history_version/，并（经用户授权）修正了工作目录。本脚本
不修改任何基线，只按磁盘实际内容生成一份可核验的迁移台账：

- 基线原哈希保持不变，作为历史证据；
- 每个迁移文件记录现位置及其哈希，若内容被授权修改，则另记原文备份位置与哈希；
- 无法用任一哈希对上基线的条目一律标记为 unproven，交由人工复核，不猜测。

用法：python tools/build_relocation_ledger.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'reports/历史迁移核对_1030ver3.json'
BASELINES = ['reports/1029-preservation-baseline.json', 'reports/1030-ver3-baseline.json']
# 纯 {路径: 哈希} 形式的清单，没有分区。
PLAIN_BASELINES = ['reports/continuation-input-hashes.json']
ARCHIVE_DIR = Path('history_version')
BACKUP_DIR = Path('history_version/original_scripts')

# 1029 基线把这些文件当作源文件冻结，但它们其实是运行器每次重写的输出（含耗时），
# 哈希必然变化。此处不靠“跳过”隐去差异，而是要求生成脚本里确有该路径字面量作为证据。
# 台账条目的 (生成脚本, 脚本里必须出现的证据片段)。文件名是拼接出来的，所以证据用
# 后缀字面量；脚本里找不到该字面量就说明不是它写的，条目会落进 unproven。
GENERATED_OUTPUTS = {
    'reports/latest-integration-tests.json': ('run_integration_checks.py', 'latest-integration-tests.json'),
    'reports/latest-integration-tests.txt': ('run_integration_checks.py', 'latest-integration-tests.txt'),
    'reports/review-continuation/new-tests.json': ('run_review_checks.py', "'-tests.json'"),
    'reports/review-continuation/new-tests.txt': ('run_review_checks.py', "'-tests.txt'"),
    'reports/review-continuation/new-frontend-tests.json': ('run_review_checks.py', "'-frontend-tests.json'"),
    'reports/review-continuation/cases-complete.json': ('review_additions/evaluate.py', 'cases-complete.json'),
    'reports/latest-frontend-tests.json': ('run_frontend_checks.py', 'latest-frontend-tests.json'),
    'reports/1029-modules-selfcheck.json': ('first_agent/vendor/eva/security/selfcheck.py', '-selfcheck'),
    'reports/1029-modules-selfcheck.txt': ('first_agent/vendor/eva/security/selfcheck.py', '-selfcheck'),
    'reports/1029-all-selfcheck.json': ('first_agent/vendor/eva/security/selfcheck.py', '-selfcheck'),
    'reports/1029-all-selfcheck.txt': ('first_agent/vendor/eva/security/selfcheck.py', '-selfcheck'),
    'reports/external-live.json': ('tools/verify_external_live.py', 'external-live.json'),
    'reports/review-continuation/rag-results.json': ('review_additions/evaluate.py', 'rag-results.json'),
    'reports/review-continuation/知识问答核对.html': ('review_additions/evaluate.py', '知识问答核对'),
}
ARCHIVE_REPORT = 'reports/启动器归档_1030.json'

# 本轮主动改动并公开记录的文件：不是“没变”，是“据实改动”，改动理由在此列明。
INTENTIONAL_EDITS = {
    '00_评委请先看.txt': '用户要求整理历史入口；旧说明留档，当前入口更新为产品行情版8807',
    '先看这里_最新版本.md': '旧版说明逐字节归档；当前说明指向8807',
    'LOCAL_AGENT_HANDOFF.md': '旧交接原文逐字节归档；当前交接指向ver4与迁移证据',
    'tests/test_tools_security_1029.py':
        '保全检查改为识别已授权迁移与运行产物；原有哈希断言保留，只增加缺失时的追溯条件',
    'review_additions/test_review.py':
        '690 文件清单检查识别授权迁移；读取文本显式指定 UTF-8',
    'review_additions/test_phase2.py': '读取文本显式指定 UTF-8，避免中文 Windows 下 GBK 解码失败',
    'review_additions/check_audit.py': '读取文本显式指定 UTF-8',
    'review_additions/delivery.py': '读取文本显式指定 UTF-8',
    'review_additions/evaluate.py': '读取文本显式指定 UTF-8',
    'review_additions/live_knowledge.py': '读取文本显式指定 UTF-8',
    'review_additions/releases.py': '读取文本显式指定 UTF-8',
    'live_indices/test_provider.py': '读取文本显式指定 UTF-8',
    'live_indices/provider.py': 'safe_url/PublicHTTP 增加可选 hosts 白名单参数；默认值仍为全局 HOSTS，指数行为不变',
    'live_indices/runtime.py': 'planning_script 增加可选额外注入块、make_server 增加可选 script 参数；默认行为不变',
    'first_agent/vendor/eva/security/adapters.py':
        '1030 Guardian 轮：扫描器默认值改 CompatibleScanner 并加能力回退；证据增加撤权与策略版本校验；新增网页审批证据桥',
    'first_agent/vendor/eva/security/injection.py':
        '1030 Guardian 轮：默认扫描器改 CompatibleScanner，消除默认构造时 ignore_code_blocks 参数导致的 TypeError',
    'modules/环境生成agent/scenario_server.py':
        '1030 API 核对轮：文档字符串原引用不存在的 API-CONTRACT(1).md，订正为根目录 API-CONTRACT.md',
    'API-CONTRACT.md':
        '1030 API 核对轮：策略版本订正为 integrated-demo-1026.1；补幂等豁免、已实现未列路由与覆盖缺口',
    'first_agent/external_services.py':
        '1030 本地模型轮：密钥改为共享路径优先并回退旧路径；本地 401 不再误报为“去官网验证”；密钥读取不再抛到 HTTP 层',
    'start_local_ai.ps1':
        '1030 本地模型轮：共享密钥、端口占用分类、启动后轮询就绪与状态文件；改为纯 ASCII 避免 PS 5.1 解析乱码',
    'start.py':
        '1030 本地模型轮：改用共用引导，不再吞掉启动器输出、不再 10 秒盲杀',
    'first_agent/service.py':
        '1030 在线核验轮：knowledge 增加可选 online_verify；仅在显式同意且无本地证据时抓取已声明的官方页面；审计只加同意布尔值',
    'web/customer-view.js':
        '1030 在线核验轮：知识卡片增加官方原文摘录与“模型改写（非引用原文）”标注；沿用 esc 转义与 https 链接限制',
    'web/external-services.js':
        '1030 在线核验轮：新增独立的官方原文核验勾选框，随 knowledge 请求发送 online_verify',
    'web/external-services.css':
        '1030 在线核验轮：原文摘录与模型改写的样式',
    '.gitignore': '排除每份安装的密钥和缓存',
    '00_评委请先看.txt': '当前入口8808与独立模型8811',
    'LOCAL_AGENT_HANDOFF.md': '新版本交接索引',
    'first_agent/external_services.py': '版本独立的回环服务、凭据与跳转限制',
    'first_agent/local_ai_bootstrap.py': '从当前版本启动并验证适配器，识别失败状态',
    'start_local_ai.ps1': '使用随包组件和相对路径，校验哈希并生成本机凭据',
    'tests/test_external_services.py': '校验便携版固定回环端口',
    'tests/test_local_model_bootstrap.py': '校验便携版管理路径仍然被拒绝',
    'tools/diagnose_local_model.py': '校验便携端口、空凭据和适配器哈希',
    'tools/build_relocation_ledger.py': '登记便携模型版本授权改动',
    'tools/build_version_ledger.py': '登记便携模型版本授权改动',
}


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def baseline_entries() -> list[tuple[str, str, str]]:
    entries = []
    for name in BASELINES:
        document = json.loads((ROOT / name).read_text(encoding='utf-8'))
        key = 'baseline' if 'baseline' in document else 'files'
        for path, digest in document[key].items():
            entries.append((name, path, digest))
    for name in PLAIN_BASELINES:
        document = json.loads((ROOT / name).read_text(encoding='utf-8'))
        for path, digest in document.items():
            entries.append((name, path, digest))
    return entries


def producer_proof(script: str, evidence: str) -> bool:
    """生成脚本里必须真的出现写入证据，否则不能声称它是运行产物。"""
    source = ROOT / script
    return source.is_file() and evidence in source.read_text(encoding='utf-8', errors='replace')


def source_of_cache(path: str) -> Path | None:
    """把 x/audit.cpython-314(2).pyc 还原成源码路径；还原不出就返回 None。

    交付时缓存被拍平，部分工具源码归位到 tool_calling/tools/，所以两个位置都试。
    """
    name = Path(path).name
    if Path(path).suffix != '.pyc' or '.cpython-' not in name:
        return None
    stem = name.split('.cpython-')[0]
    parent = Path(path).parent
    for candidate in (parent / (stem + '.py'), parent / 'tools' / (stem + '.py')):
        if (ROOT / candidate).is_file():
            return candidate
    return None


def build() -> dict:
    relocated, generated, updated, edited, absent_cache, unproven = [], [], [], [], [], []
    incoming_missing = []
    preservation = json.loads((ROOT / 'reports/1029-preservation-baseline.json').read_text(encoding='utf-8'))
    for item in preservation['incoming']:
        target = ROOT / item['target']
        if target.exists():
            current = sha256(target)
            if current != item['sha256']:
                # 与基线循环同一套标准：已登记的主动改动不再算未证实，
                # 未登记的一律仍算未证实。基线文件本身不改写。
                if item['target'] in INTENTIONAL_EDITS:
                    edited.append({'baseline': 'reports/1029-preservation-baseline.json',
                                   'path': item['target'], 'baseline_sha256': item['sha256'],
                                   'current_sha256': current,
                                   'reason': INTENTIONAL_EDITS[item['target']]})
                else:
                    unproven.append({'baseline': 'reports/1029-preservation-baseline.json',
                                     'path': item['target'], 'state': '交付文件被改动',
                                     'baseline_sha256': item['sha256'], 'current_sha256': current})
            continue
        incoming_missing.append(item['target'])
        source = source_of_cache(item['target'])
        if source and (ROOT / source).is_file():
            # 这些 pyc 是下载重名残留（(1)/(2)/(3)/(4)），从未真实交付；源码在，行为由源码与测试保证。
            absent_cache.append({'baseline': 'reports/1029-preservation-baseline.json',
                                 'path': item['target'], 'source': str(source),
                                 'source_sha256': sha256(ROOT / source),
                                 'reason': '未交付的编译缓存；同名源码存在，不补造缓存文件'})
            continue
        unproven.append({'baseline': 'reports/1029-preservation-baseline.json', 'path': item['target'],
                         'state': '缺失且找不到对应源码'})

    seen = set()
    archives = json.loads((ROOT / ARCHIVE_REPORT).read_text(encoding='utf-8'))['path_updates']
    current_archive = ROOT / 'reports/启动器归档_1030ver4.json'
    if current_archive.exists():
        archives += json.loads(current_archive.read_text(encoding='utf-8'))['path_updates']
    authorized = {item['original_sha256'].lower(): item for item in archives}
    for source, path, digest in baseline_entries():
        if (path, digest) in seen:
            continue
        seen.add((path, digest))
        current = ROOT / path
        if current.exists():
            if sha256(current) == digest:
                continue
            producer = GENERATED_OUTPUTS.get(path)
            if producer and producer_proof(*producer):
                generated.append({'baseline': source, 'path': path, 'producer': producer[0],
                                  'evidence': producer[1], 'baseline_sha256': digest,
                                  'current_sha256': sha256(current),
                                  'reason': '运行器每次重写的测试输出（含耗时），不能作为源文件冻结对象'})
                continue
            record = authorized.get(digest.lower())
            if record and record['updated_sha256'].lower() == sha256(current):
                updated.append({'baseline': source, 'path': path, 'proof': ARCHIVE_REPORT,
                                'file': record['file'], 'change': record['change'],
                                'baseline_sha256': digest, 'current_sha256': sha256(current),
                                'reason': '基线取自启动器修正之前；原文哈希与改后哈希均由归档报告逐字节记录'})
                continue
            if path in INTENTIONAL_EDITS:
                edited.append({'baseline': source, 'path': path,
                               'baseline_sha256': digest, 'current_sha256': sha256(current),
                               'reason': INTENTIONAL_EDITS[path]})
                continue
            unproven.append({'baseline': source, 'path': path, 'state': '内容被改动',
                             'baseline_sha256': digest, 'current_sha256': sha256(current)})
            continue
        archived = ARCHIVE_DIR / path
        backup = BACKUP_DIR / (path + '.txt')
        current_sha, backup_sha = sha256(ROOT / archived), sha256(ROOT / backup)
        if digest not in (current_sha, backup_sha):
            unproven.append({'baseline': source, 'path': path, 'state': '缺失且无法追溯',
                             'baseline_sha256': digest, 'current_sha256': current_sha,
                             'backup_sha256': backup_sha})
            continue
        relocated.append({
            'baseline': source,
            'path': path,
            'baseline_sha256': digest,
            'current': str(archived),
            'current_sha256': current_sha,
            'current_is_baseline': current_sha == digest,
            'backup': str(backup) if backup.is_file() else None,
            'backup_sha256': backup_sha,
            'reason': '内容未变，仅位置迁入 history_version' if current_sha == digest
                      else '经用户授权修正工作目录；原文逐字节保存在 original_scripts',
        })
    # 同一路径可能同时出现在 incoming 与基线两个循环里，按路径去重后再输出。
    edited = list({item['path']: item for item in edited}.values())
    return {
        'generated_by': 'tools/build_relocation_ledger.py',
        'purpose': '证明移出根目录的历史文件内容未被篡改，供保全检查识别授权迁移。',
        'not_a_baseline_edit': '两个基线 JSON 未改动；本台账只新增映射，不改写历史哈希。',
        'relocated': sorted(relocated, key=lambda item: item['path']),
        'authorized_updates': sorted(updated, key=lambda item: item['path']),
        'generated_outputs': sorted(generated, key=lambda item: item['path']),
        'intentional_edits': sorted(edited, key=lambda item: item['path']),
        'absent_cache': sorted(absent_cache, key=lambda item: item['path']),
        'incoming_missing': sorted(incoming_missing),
        'unproven': unproven,
        'summary': {'relocated': len(relocated), 'authorized_updates': len(updated),
                    'generated_outputs': len(generated), 'intentional_edits': len(edited),
                    'absent_cache': len(absent_cache), 'incoming_missing': len(incoming_missing),
                    'unproven': len(unproven)},
    }


def audit(manifest: dict[str, str]) -> dict:
    """按台账判定任意 {路径: 期望哈希} 清单，返回问题列表。

    未变更、已授权迁移、已登记改动、运行产物、未交付缓存都可追溯；其余一律算问题，
    由调用方断言为空。两个保全测试共用这一套判定，避免各写一版标准。
    """
    ledger = build()
    relocated = {item['path']: item for item in ledger['relocated']}
    updates = {item['path']: item for item in ledger['authorized_updates']}
    outputs = {item['path'] for item in ledger['generated_outputs']}
    edits = {item['path'] for item in ledger['intentional_edits']}
    caches = {item['path'] for item in ledger['absent_cache']}
    problems = [dict(item, problem=item['state']) for item in ledger['unproven']]
    for path, digest in sorted(manifest.items()):
        current = ROOT / path
        if current.exists() and sha256(current) == digest:
            continue
        if path in relocated:
            if digest not in (relocated[path]['current_sha256'], relocated[path]['backup_sha256']):
                problems.append({'path': path, 'problem': '迁移后哈希对不上基线'})
        elif path in updates:
            if updates[path]['baseline_sha256'] != digest:
                problems.append({'path': path, 'problem': '授权改动登记的基线哈希不符'})
        elif path in outputs:
            if not (current.is_file() and current.stat().st_size > 0):
                problems.append({'path': path, 'problem': '运行产物缺失或为空'})
        elif path in caches or path in edits:
            continue
        else:
            problems.append({'path': path, 'problem': '既非原样存在，也无追溯记录'})
    return {'problems': problems, 'ledger': ledger}


def main() -> int:
    ledger = build()
    OUTPUT.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"迁移台账已写入 {OUTPUT.relative_to(ROOT)}：迁移 {ledger['summary']['relocated']}，"
          f"运行产物 {ledger['summary']['generated_outputs']}，未证实 {ledger['summary']['unproven']}")
    return 0 if not ledger['unproven'] else 1


if __name__ == '__main__':
    sys.exit(main())
