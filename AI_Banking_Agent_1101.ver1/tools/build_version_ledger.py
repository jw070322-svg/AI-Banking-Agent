#!/usr/bin/env python3
"""Compare the current tree against a version baseline and classify every change.

本版新增的每个文件、改动的每个文件都要能说出理由；说不出的不静默放过，而是留在
unproven 里让命令以非零码退出。基线本身只读，不做任何改写。

用法：python tools/build_version_ledger.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'reports/1030-ver4-baseline.json'
OUTPUT = ROOT / 'reports/1030-ver4-change-ledger.json'
SKIP_DIRS = {'__pycache__', 'runtime'}
SKIP_SUFFIX = {'.pyc', '.sqlite3'}

# 本轮对既有文件所做的改动，逐条写明理由。
REASONS = {
    'README.md': '1101 赛题交付新增当前版本启动与材料导航',
    '00_评委请先看.txt': '用户要求归档历史入口；更新唯一启动器为产品行情版8807，旧说明已留档',
    '先看这里_最新版本.md': '旧8805说明逐字节归档；根目录指向当前产品行情版8807',
    'LOCAL_AGENT_HANDOFF.md': '继承的历史交接原文已归档；根目录提供当前版本与最新迁移证据入口',
    'reports/启动器归档_1030ver4.json': '本轮用户授权迁移清单，包含原文哈希及历史启动器工作目录修正证据',
    'reports/启动器整理核验_1030ver4.json': '启动器唯一性、依赖、哈希及保全检查结果',
    'logs/creation_1030_ver4_archive.jsonl': '本轮历史文件整理八字段创作日志',
    'live_indices/provider.py': 'safe_url/PublicHTTP 增加可选 hosts 白名单；默认值仍为全局 HOSTS，指数行为不变',
    'live_indices/runtime.py': 'planning_script 增加可选注入块、make_server 增加可选 script；默认行为不变',
    'tools/build_relocation_ledger.py': '登记本轮主动改动与新增运行产物，保全检查据此判定',
    'reports/历史迁移核对_1030ver3.json': '迁移台账按新登记重新生成',
    'reports/latest-integration-tests.json': '运行器重写的测试输出',
    'reports/latest-integration-tests.txt': '运行器重写的测试输出',
    'reports/latest-frontend-tests.json': '运行器重写的测试输出',
    'reports/review-continuation/new-tests.json': '运行器重写的测试输出',
    'reports/review-continuation/new-tests.txt': '运行器重写的测试输出',
    'reports/review-continuation/new-frontend-tests.json': '运行器重写的测试输出',
    'reports/review-continuation/cases-complete.json': '评测脚本重写的输出',
    'reports/1030-ver4-baseline.json': '本版基线自身',
    'reports/latest-integration-tests.json': '运行器重写的测试输出',
    'live_products/__init__.py': '产品行情包入口',
    'live_products/provider.py': 'ETF 场内公开行情；场外基金与银行理财只产出核验入口，不联网、不补造',
    'live_products/runtime.py': '在产品服务的 market 响应里追加 product_quote_selection，不动 product_observations',
    'live_products/cards.js': '价格与评分净值并列渲染；无行情产品显示原因与人工核验链接',
    'live_products/test_provider.py': '产品行情门禁、撞码回归、解析与回退用例',
    'live_products/test_runtime.py': '产品接入的会话、事务边界、审计与注入用例',
    'tests_frontend/product-quotes.cjs': '产品卡片渲染、转义与无行情文案用例',
    'start_live_product_quotes.py': '8807 启动入口，独立账本与产品审计文件',
    '启动产品行情版.bat': '双击入口；带 -X utf8 避免中文 Windows 编码问题',
    'reports/product-quote-probe/etf_510300_last.txt': '同花顺公开分时冻结响应，供离线回归',
    'reports/product-quote-probe/PROVENANCE.json': '冻结响应的来源、抓取时间与哈希',
    'tools/build_version_ledger.py': '本版变更台账工具：新增/改动必须附理由，否则非零退出',
    'reports/1030-ver4-change-ledger.json': '台账工具自身的输出',
    'HANDOFF_1030_PRODUCT_QUOTES.json': '本轮交接：状态、证据、测试与遗留',
    'HANDOFF_1030_GUARDIAN_PAUSED.json': '上一轮额度暂停交接，本版基线生成之后新建；本轮据其继续，原文不改',
    '产品实时行情接入说明_1030.md': '接入边界、口径分工、防错设计与已知限制',
    'logs/creation_1030_product_quotes.jsonl': '本轮八字段创作日志',
    # 1030 Guardian 接线修复轮
    'first_agent/vendor/eva/security/adapters.py':
        '修复合规适配器扫描器接口不兼容；证据增加撤权/策略版本；新增网页审批证据桥与验票就绪判定',
    'first_agent/vendor/eva/security/injection.py':
        '默认扫描器改 CompatibleScanner，修复默认 PromptInjectionGuard 的 TypeError',
    'first_agent/vendor/eva/security/verification.py':
        '新增验证闸门：13 项检查、证据报告、源码哈希票、build_verified_runtime',
    'tests/test_guardian_1030.py': 'Guardian 连接/放行/拒绝/异常/撤权/过期/篡改/重放/未知回执与端到端用例',
    'reports/guardian-1030ver4-verification.json': '验证闸门逐项结果与源码哈希证据',
    'reports/1029-modules-selfcheck.json': '模块自检运行器重写的输出',
    'reports/1029-modules-selfcheck.txt': '模块自检运行器重写的输出',
    'logs/creation_1030_guardian.jsonl': 'Guardian 轮八字段创作日志',
    'HANDOFF_1030_GUARDIAN_COMPLETE.json': 'Guardian 轮交接：完成项、证据与剩余边界',
    'reports/归档补齐_1030ver4.json': 'history_version 缺口补齐的来源与哈希清单',
    'tools/backfill_history_versions.py': 'history_version 缺口补齐工具：逐字节复制并重算哈希，不覆盖已存在文件',
    'history_version/from_previous_versions/MANIFEST.json': '补齐清单：来源路径、哈希、大小与用途',
    'history_version/from_previous_versions/1025.ver1/handoff/HANDOFF.json': '1025.ver1 交接包，此前全仓缺失',
    'history_version/from_previous_versions/1025.ver1/handoff/HANDOFF.md': '1025.ver1 交接说明，此前全仓缺失',
    'history_version/from_previous_versions/1025.ver1/handoff/quota_monitor_2026-10-25/HANDOFF.json': '1025.ver1 额度监控副本，此前全仓缺失',
    'history_version/from_previous_versions/1025.ver1/handoff/quota_monitor_2026-10-25/HANDOFF.md': '1025.ver1 额度监控说明，此前全仓缺失',
    'history_version/from_previous_versions/1026.ver1/LOCAL_AGENT_HANDOFF.md': '1026.ver1 交接历史修订版',
    'history_version/from_previous_versions/1026.ver2/LOCAL_AGENT_HANDOFF.md': '1026.ver2 交接历史修订版',
    'history_version/from_previous_versions/1027.ver1/LOCAL_AGENT_HANDOFF.md': '1027.ver1 交接历史修订版',
    'history_version/from_previous_versions/1027.ver2/LOCAL_AGENT_HANDOFF.md': '1027.ver2 交接历史修订版',
    'history_version/from_previous_versions/1027.ver3/LOCAL_AGENT_HANDOFF.md': '1027.ver3 交接历史修订版',
    'history_version/from_previous_versions/1027.ver4/LOCAL_AGENT_HANDOFF.md': '1027.ver4 交接历史修订版',
    'history_version/from_previous_versions/1027.ver5/LOCAL_AGENT_HANDOFF.md': '1027.ver5 交接历史修订版',
    'tools/build_relocation_ledger.py': '登记本轮 Guardian 改动，保全检查据此判定',
    'API-CONTRACT.md': '按实际代码订正策略版本、端口与缺失路由清单',
    'tools/audit_api_endpoints_1030ver4.py': '内部路由与契约文档的静态双向核对工具',
    'tools/verify_external_endpoints_1030ver4.py': '外部数据端点只读实测与冻结样本工具',
    'reports/api-endpoints-1030ver4.json': '路由双向差集核对结果',
    'reports/external-endpoints-1030ver4/PROVENANCE.json': '外部端点实测来源、状态、签名与哈希',
    'reports/external-endpoints-1030ver4/ths_index_directory.txt': '同花顺指数目录冻结响应，供离线回归',
    'reports/external-endpoints-1030ver4/ths_zs_1B0001.txt': '同花顺指数分时冻结响应（000001.SH）',
    'reports/external-endpoints-1030ver4/ths_hs_510300.txt': '同花顺ETF分时冻结响应（510300.SH）',
    'reports/external-endpoints-1030ver4/wind_index_page.txt': 'Wind 官网页面冻结响应',
    'reports/external-endpoints-1030ver4/wind_detail_js.txt': 'Wind 官网脚本冻结响应',
    'modules/环境生成agent/scenario_server.py': '文档字符串引用订正为根目录 API-CONTRACT.md',
    # 1030 本地模型接入修复轮
    'first_agent/external_services.py':
        '本地模型密钥改为共享路径优先+旧路径回退；本地 401 映射为新状态 auth_rejected；抽出发头/错误映射纯函数便于离线测试',
    'first_agent/local_ai_bootstrap.py': '新增本地模型引导：就绪快路径、适配器实证、端口冲突只报告不强杀',
    'start_local_ai.ps1': '共享密钥、端口占用分类、启动后轮询就绪、状态文件；纯 ASCII 以兼容 Windows PowerShell 5.1',
    'start.py': '改用共用引导并在失败时打印真实原因',
    'start_live_product_quotes.py': '8807 演示入口启动前自动拉起并核验本地模型',
    'start_live_indices.py': '8806 对照入口同样拉起本地模型',
    'tools/diagnose_local_model.py': '一条命令定位本地模型链路的断点',
    'tests/test_local_model_bootstrap.py': '密钥优先级、状态映射、引导状态机与“拒绝用基础模型顶替”不变量的离线测试',
    'reports/external-live.json': '验收脚本重写的实测输出',
    'reports/review-continuation/rag-results.json': '105 题评测脚本重写的输出',
    'reports/review-continuation/知识问答核对.html': '105 题评测脚本重写的核对页面',
    'HANDOFF_1030_LOCAL_AI_FIX.json': '本轮交接：根因、修复、证据与边界',
    'logs/creation_1030_local_ai.jsonl': '本轮八字段创作日志',
    # 1030 官方原文在线核验轮
    'first_agent/online_verification.py': '官网在线核验：stdlib HTMLParser 提取标题/元数据/正文块，按术语字面命中选段，输出 six 状态与可核验引用；无第三方依赖',
    'first_agent/external_services.py': 'request 增加可传入的 hosts（默认行为不变）与 complete() 供核验改写复用；本地请求的跳转规则保持原样',
    'first_agent/service.py': 'knowledge 增加 online_verify 分支与兜底步骤记录；审计只记同意布尔值，不记问题原文',
    'web/customer-view.js': '知识卡片增加官方原文摘录与模型改写标注',
    'web/external-services.js': '增加官方原文核验勾选框并随 knowledge 请求发送',
    'web/external-services.css': '原文摘录与模型改写样式',
    'tests/test_online_verification.py': '核验链路的离线用例：解析、选段、主机白名单、PDF 回退、改写校验、证据冻结与授权前不外发',
    'tests_frontend/online-verification.cjs': '核验卡片渲染、转义与改写标注用例',
    'API-CONTRACT.md': '补充 knowledge 的 online_verify 参数、六种状态与抓取边界',
    'HANDOFF_1030_ONLINE_VERIFY.json': '本轮交接：设计、证据、实测与边界',
    'logs/creation_1030_online_verify.jsonl': '本轮八字段创作日志',
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


def current_files():
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts) or path.suffix in SKIP_SUFFIX:
            continue
        yield rel.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()


def archive_evidence(baseline, now):
    """Recognize only paths and exact hashes recorded in the user-authorized archive."""
    report = ROOT / 'reports/启动器归档_1030ver4.json'
    if not report.exists():
        return {}, {}, []
    document = json.loads(report.read_text(encoding='utf-8'))
    updates = {row['file']: row for row in document.get('path_updates', [])}
    relocated, targets, errors = {}, {}, []
    for row in document['moved']:
        source, target, expected = row['from'], row['to'], row['sha256']
        # Historical baseline remains the authority; the manifest alone is not proof.
        if baseline.get(source) != expected or not target.startswith('history_version/') or '..' in Path(target).parts:
            errors.append(source)
            continue
        valid = now.get(target) == expected
        update = updates.get(source)
        backup = update.get('original') if update else None
        if update:
            valid = (backup is not None and backup.startswith('history_version/original_scripts/')
                     and '..' not in Path(backup).parts and now.get(backup) == expected
                     and update['original_sha256'] == expected
                     and now.get(target) == update['updated_sha256'])
        if not valid:
            errors.append(source)
            continue
        proof = {'path': source, 'current': target, 'baseline_sha256': expected,
                 'current_sha256': now[target], 'backup': backup,
                 'proof': 'reports/启动器归档_1030ver4.json'}
        if source not in now:
            relocated[source] = proof
        targets[target] = '用户授权历史归档；原路径与基线哈希匹配，内容或原文备份已核验'
        if backup:
            targets[backup] = '历史启动器修正相对目录前的逐字节备份，与原基线哈希匹配'
    return relocated, targets, errors


def build():
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))['files']
    now = dict(current_files())
    relocated, targets, archive_errors = archive_evidence(baseline, now)
    reasons = REASONS | targets
    added = sorted(p for p in now if p not in baseline)
    modified = sorted(p for p in now if p in baseline and now[p] != baseline[p])
    missing = sorted(p for p in baseline if p not in now and p not in relocated)
    unproven = sorted(set([p for p in added + modified if p not in reasons] + archive_errors))
    return {
        'baseline': str(BASELINE.relative_to(ROOT)),
        'generated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'summary': {'unchanged': len(now) - len(added) - len(modified), 'added': len(added),
                    'modified': len(modified), 'relocated': len(relocated), 'missing': len(missing), 'unproven': len(unproven)},
        'added': [{'path': p, 'reason': reasons.get(p)} for p in added],
        'modified': [{'path': p, 'reason': reasons.get(p)} for p in modified],
        'relocated': list(relocated.values()),
        'missing': missing,
        'unproven': unproven,
    }


def main() -> int:
    ledger = build()
    OUTPUT.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    s = ledger['summary']
    print(f"变更台账已写入 {OUTPUT.relative_to(ROOT)}：未变 {s['unchanged']}，新增 {s['added']}，"
          f"改动 {s['modified']}，缺失 {s['missing']}，未证实 {s['unproven']}")
    return 0 if not ledger['unproven'] and not ledger['missing'] else 1


if __name__ == '__main__':
    sys.exit(main())
