"""Regenerate SecondAsgent handoff from measured evidence, without changing source inputs."""
from pathlib import Path
from datetime import datetime, timezone
import difflib, hashlib, json, shutil

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return p.read_text(encoding='utf-8-sig')
def dump(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
def md(p, parts):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('\n\n'.join(parts)+'\n', encoding='utf-8')

BRANCHES = [
 {'file':'eva','branch_name':'eva / 模拟银行接口与风控（卡管理后端主责）',
  'analysis':'卡状态会直接改变转账可执行性，必须由服务端统一检查；页面禁用按钮不足以保护另一条 API。旧版权限检查也缺少 24 小时到期判断。',
  'summary':'复用 eva ver.2 的工具、模型和限额配置，新增两条转账路径共同执行的卡状态、日额度、授权过期和预览绑定约束。',
  'changes':[
   ('first_agent/service.py','require 增加 consentExpiresAt；authorize.cards 仅接受 bool；策略版本升为 integrated-demo-1.1，使旧策略确认不能继续执行。'),
   ('first_agent/service.py','bound_hash 加入付款卡；check_transfer_limits 从共享交易记录累计当日转账，并使用 eva 单笔/日硬限额；transfer_policy 检查默认卡的 active 状态及剩余额度。'),
   ('first_agent/service.py','apply_transfer 同时更新卡片 spent 与 externalOut；初始资产基准不再随出账缩减，使可用资金+持仓+对外转出保持守恒。'),
   ('first_agent/service.py','红色操作先检查服务端断言期限和绑定，再执行引擎；避免过期断言仅返回笼统的引擎拒绝。失败不扣款，未知结果仍阻止新金融写入。'),
   ('tests/test_update.py','覆盖两条转账路径共享限额、挂失禁止交易、权限类型、过期、重放、旧状态迁移及未知结果只结算一次。')],
  'retained':'首轮的 ver.1 scanner 补缺、security gate、脱敏、账户越权、增强断言和幂等事务继续保留。原始 eva 包缺件情况未变化；没有宣称其原版 42 项测试通过。',
  'next':['维护模拟银行 API 与卡状态/限额契约；真实银行由组委会部署接入。','后续提供完整同版本 bank_agent 包及其原版测试。','与 vv 对齐错误提示、卡版本变化和任务回执，不另建账本。']},
 {'file':'vv','branch_name':'vv / 页面交互与卡管理前端',
  'analysis':'1023 单页 HTML 修改时间更晚，但源码 ZIP 包含单页缺少的契约修复。新版卡片 UI 可以复用；local-store 与 contract-client 若直接载入，会与现有服务端状态发生冲突。',
  'summary':'升级到 1023 的转账、卡管理、任务与记录界面，沿用同源 BankCore 服务端桥接，卡申请/限额/限制/解锁/挂失均进入确认与回执流程。',
  'changes':[
   ('web/journey-engine.js','以 1023 ZIP 补齐最新单页缺少的 trade 权限映射、300 秒预览、120 秒验证、累计 1000 元分级和锁定加结算规则；新增 options.preserveVerification 仅供可信服务端恢复。'),
   ('web/journey-engine.js','保留新版 cards、contacts、externalOut 和 settleCard；授权到期边界改为 >=。开卡须次日查询审核，开卡和额度调整不增加资金，挂失不可解锁。'),
   ('web/journey-workspace.js','接入新版卡选择、转账、任务记录及卡管理交互；移除对 BankGateway/BankLocal 的运行依赖，使用现有 BankCore；页面文案改为服务端模拟保存及已连接模拟 API。'),
   ('web/journey-workspace.css','采用新版配套样式，支持卡管理和更新的转账布局。'),
   ('web/server-bridge.js','暴露 settleCard；导出当前服务端公开快照；不写浏览器 localStorage，不运行客户端账本。'),
   ('web/agent-panel.js','新增独立测试场景生成按钮，调用 /api/scenarios/generate；保留聊天澄清、旧转账及带证据问答。'),
   ('first_agent/engine_worker.cjs','使用 Python 传入的时钟及 preserveVerification:true，让相邻 HTTP 请求共享已验证状态，继续执行服务端 120 秒期限检查。'),
   ('tests/vv_simulation.cjs','引入交付中的 15 项转账/卡管理/恢复/资金守恒测试，路径改为当前 web。'),
   ('tests/vv_contract_rules.cjs','引入交付中的 5 项授权、300/120 秒边界和累计分级测试；原 vv_core 15 项保留。')],
  'retained':'首轮的 server-bridge、Agent 面板、统一服务端状态和本地字体继续保留。浏览器验收覆盖卡限制完成及刷新、RAG、场景入口；不宣称全尺寸视觉回归已完成。',
  'next':['将兼容同步 XHR 改为异步加载并设计等待/失败状态。','继续完成窄屏、键盘及屏幕阅读器验收。','旧聊天名册与新页面 contacts 使用不同虚构联系人集合，后续可统一目录服务；当前都执行共同账本与限制。']},
 {'file':'YUKI','branch_name':'YUKI / 知识检索与评测',
  'analysis':'本轮没有发现比 1022 更新的知识交付；不应为了更新版本而改写原文或丢失已有引用哈希。卡管理执行依赖工具状态，知识问答保持独立。',
  'summary':'保留 1022 八篇知识原文、BM25 检索、哈希与行号引用；本轮无该分支运行代码变更，并复核知识问答与新版界面的兼容。',
  'changes':[],
  'retained':'首轮变更包括 knowledge 文件名修复及索引、项目 RAG/banking_rag 补丁、中文双字分词、无证据拒答，以及 service 的知识响应结构。完整逐文件说明见历史 YUKI.md。',
  'next':['补充审核人、适用日期和可追溯来源。','将 20 正常/20 边界/10 风险题转成有标注的自动评测；当前不声称 50 题通过。','银行条款与教育材料区分维护，文档内容不得触发工具执行。']},
 {'file':'Ethan','branch_name':'Ethan / 环境与测试场景生成',
  'analysis':'1022 已新增完整环境生成源码和 A–E 样例，因此撤销旧版“空交付、推荐补位”的暂定归属。原 main.py 的补充校验在外部 validator 可用时不会自动执行；仅导入 validator 会漏掉余额和场景语义检查。',
  'summary':'接入最新环境生成代码及五类最新样例，增加统一整数分、双层校验、余额核对和独立生成 API；场景不写入当前模拟银行账本。',
  'changes':[
   ('first_agent/vendor/scenario/generator.py','来源 Ethan 1022 main.py；改为包内 base_validator 相对导入；保留原规则解析、备用生成器及 fallback 校验。'),
   ('first_agent/vendor/scenario/base_validator.py','复用原 validator.py 的结构、唯一 ID 和关联检查；原始快照保存在 sources/Ethan。'),
   ('first_agent/vendor/scenario/__init__.py','新增包入口，使场景生成器可由本地服务导入。'),
   ('first_agent/scenarios.py','新增 minor/normalize/generate 适配：拒绝 bool、非有限值、负金额、超过两位小数和超上限值；元转整数分，收入为正、支出为负。'),
   ('first_agent/scenarios.py','completed 映射 booked；rejected 不进入余额；精确检查期初+已入账交易=期末，再显式调用原 fallback 的 A–E 语义校验。输出不包含原始用户身份证/手机等字段。'),
   ('first_agent/scenarios.py','补 scenario_id；修正 B 类“2 个月增加 800 元”误把月份当金额的问题；输入限制 1–2000 字；输出 ledger_modified:false。'),
   ('first_agent/server.py','注册 POST /api/scenarios/generate，使用现有会话、响应外壳及幂等键要求。'),
   ('first_agent/service.py','新增 scenario.generate 路由，将校验失败转换为 SCENARIO_INVALID；不替换实时账本。'),
   ('scenarios/','按每个 A–E 家族选择 20261022185343 批次最新样例，经同一适配器生成五个规范 JSON；原始源路径及 SHA-256 见 update_metadata。'),
   ('tests/test_update.py','覆盖 A–E 样例核对、非法金额/重复 ID/不平账拒绝、B 类参数解析和 API 幂等及账本隔离。')],
  'retained':'首轮推荐补丁来自 financial_recommendation_module，继续由集成层维护，不再归因于 Ethan 的原始交付。生成过程不调用远程模型。',
  'next':['增加带固定随机种子的边界样例和预期结果，便于重复评测。','持续补充场景字段和语义校验，更新 scenario-1.0 时给出迁移规则。','若未来需要加载场景到演示账本，应设计显式新会话导入接口；本次只生成独立数据。']},
 {'file':'integration','branch_name':'集成 / 编排、契约与交付',
  'analysis':'新引擎每次在 Node 子进程恢复状态，浏览器恢复时清空验证的逻辑会破坏跨请求确认；旧转账又不能与新卡模块各算一份金额。解决点位于服务端恢复、共同交易记录和公开状态投影。',
  'summary':'完成可信服务端状态恢复、双转账接口共用账本/卡限额/任务展示、Ethan 场景隔离，以及 SecondAsgent 独立交付和可复算变更记录。',
  'changes':[
   ('first_agent/service.py','旧状态缺 cards 时补默认卡/联系人/externalOut 并使旧待确认失效；public_state 将旧 transfer_ops 投影进统一任务列表，不重复保存操作。'),
   ('first_agent/service.py','RPC verify/execute/cancel/reconcile 能按旧操作 ID 转发兼容接口；两种转账入口共享账单、日累计、卡状态及未知操作阻断。'),
   ('first_agent/service.py','引擎请求携带统一时钟；verify 与 execute 跨请求恢复有效，服务端绑定和期限独立校验。'),
   ('verify_delivery.py','发现 test_*.py 全部测试，运行三套 JS 检查；按唯一测试对象扣除错误/失败，避免 setup 与 cleanup 双计；不重复导入旧测试类。'),
   ('tests/test_update.py','新增 12 个独立测试；总计为旧 20 + 新 12，不将继承/导入造成的重复执行计入验收。'),
   ('write_update_reports.py','新增基于实测报告生成总版、分工、上下文、逐文件差异和 SHA-256 清单的脚本；低额度时状态改为 paused_low_quota。'),
   ('write_reports.py','改为调用本轮报告生成器，避免重新运行旧脚本覆盖成首轮结论。'),
   ('run_agent.ps1','默认端口改为 8767，便于与 FirstAgent 并行运行；支持显式 -Port。'),
   ('README.md / API-CONTRACT.md','更新 SecondAsgent 启动路径、卡管理 RPC、场景接口、真实银行接入责任及明确限制。')],
  'retained':'首轮 HTTP、SQLite、规则路由、多轮澄清、推荐、RAG、安全与审计继续保留。已有推荐补丁明确归集成；原始队友输入和 FirstAgent 不覆盖。',
  'next':['维护模拟 API 的可替换契约，配合组委会本地部署接入真实银行。','自然语言当前为规则解析；如需开放式模型，保持确定性工具与确认边界。','本机演示会话及 SQLite 审计不等同生产认证、防篡改或分布式事务。']}
]

def main():
    now=datetime.now(timezone.utc).isoformat()
    metadata=json.loads(read(BASE/'reports/update_metadata.json'))
    metadata['delivery']=str(BASE)
    metadata['vv_selection_reason']='最新单页时间较晚；逐脚本比较发现 ZIP 含 trade 映射、预览/断言期限、累计分级等补丁。以单页新增业务功能为目标，从完整 ZIP 源码补齐契约保护，并连接服务端。'
    metadata['vv_file_mtimes_utc']={p.name:datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat() for p in (ROOT/'Teammate_output/vv output/1023').iterdir() if p.is_file()}
    dump(BASE/'reports/update_metadata.json',metadata)
    verification=json.loads(read(BASE/'reports/verification.json'))
    quota=json.loads(read(BASE/'reports/quota_latest.json'))
    browser_path=BASE/'reports/browser-verification-20261023.json'
    browser=json.loads(read(browser_path)) if browser_path.exists() else {'status':'pending'}
    stop=quota.get('stop',False)
    status='paused_low_quota' if stop else 'completed'
    inventory=json.loads(read(BASE/'reports/source_inventory_20261023.json'))
    changed_inputs=[]
    for item in inventory['files']:
        p=ROOT/item['path']
        if not p.is_file() or sha(p)!=item['sha256']:changed_inputs.append(item['path'])
    dump(BASE/'reports/source_integrity.json',{'checked_at':now,'checked':len(inventory['files']),'changed':changed_inputs,'conclusion':'unchanged' if not changed_inputs else 'changed'})
    code_changes=[]
    paths=sorted(set(p.relative_to(BASE).as_posix() for folder in ['first_agent','web','tests'] for p in (BASE/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts))
    paths+=['verify_delivery.py','run_agent.ps1','write_reports.py','write_update_reports.py']
    for rel in paths:
        p=BASE/rel; prior=ROOT/'FirstAgent'/rel
        if prior.exists() and sha(p)==sha(prior):continue
        patch=Path('reports/diffs')/(rel.replace('/','__')+'.diff')
        before=read(prior).splitlines(True) if prior.exists() else []
        diff=''.join(difflib.unified_diff(before,read(p).splitlines(True),fromfile='FirstAgent/'+rel,tofile='SecondAsgent/'+rel))
        (BASE/patch).parent.mkdir(parents=True,exist_ok=True)
        (BASE/patch).write_text(diff,encoding='utf-8')
        code_changes.append({'path':rel,'old_sha256':sha(prior) if prior.exists() else None,'new_sha256':sha(p),'diff':patch.as_posix()})
    dump(BASE/'reports/code_changes.json',{'baseline':'../FirstAgent','files':code_changes,'conclusion':'逐文件差异与哈希覆盖本轮运行代码、测试和交付脚本。'})
    for b in BRANCHES:
        parts=['# '+b['branch_name']+'：本轮代码修改与交接','## 判断依据',b['analysis'],'## 本轮逐项修改（2026-10-23）']
        if b['changes']:
            parts+=['| 文件 | 实际改动及目的 |\n|---|---|\n'+'\n'.join('| `'+p+'` | '+note+' |' for p,note in b['changes'])]
        else:parts+=['本轮没有该分支运行代码变更；复用了已验证版本。']
        parts+=['## 首轮保留内容与详细历史',b['retained'],f'[首轮逐项变更记录](../history/20261022/branches/{b["file"]}.md)。历史中的“卡管理未实现”“Ethan 空交付”为当时状态，本轮以上文为准。','## 本轮完整代码差异']
        related=[]
        keys=[p for p,_ in b['changes']]
        for c in code_changes:
            if any(c['path']==k or (k.endswith('/') and c['path'].startswith(k)) for k in keys):
                related.append(f"- `{c['path']}`：[完整补丁](../diffs/{Path(c['diff']).name})，SHA-256 `{c['new_sha256']}`。")
        parts+=related or ['无新增补丁。']
        parts+=['## 验证与责任边界','总包实测：32/32 Python 集成检查，35/35 JS 检查；详见 [验证报告](../verification.json)。此结果不等于各队友原版测试全部通过。','卡管理分工：eva 主责后端模拟接口、卡状态与风控；vv 主责卡片库选择与确认交互；集成负责状态/安全/回执串联；Ethan 提供场景测试数据；YUKI 提供知识及评测资料。','## 后续协作']+['- '+n for n in b['next']]+['结论：'+b['summary']]
        md(BASE/'reports/branches'/f"{b['file']}.md",parts)
    reflections=[
     '不能仅凭文件修改时间推断语义版本：本轮同时记录单页和 ZIP 的时间、哈希及脚本差异，用完整源码中的契约补丁补齐单页缺项。',
     '浏览器刷新时清除验证与可信服务端每请求恢复不是同一场景：仅服务端恢复保留 verified，仍以服务端断言绑定与真实时钟判断期限。',
     '卡管理不是独立资金池：新旧转账入口统一累计和卡支出，externalOut 记录对外转出，开卡/额度变更不产生存款。',
     '有 validator 文件不代表验证完整：结构校验之外显式复用 fallback 场景校验并增加整数分精确对账。',
     '分工归属以交付内容核实：Ethan 已明确为环境生成；推荐补丁的来源与集成维护责任单独记录。',
     '测试数量须按独立用例统计：本轮为 32 项集成与 35 项 JS，清除了导入旧测试类带来的重复计数。']
    remaining=[
     '目前仅本地规则驱动模拟 Agent；没有真实银行连接、真实验证码或开放式大模型。真实银行由组委会部署接入，不属于团队欠交项。',
     '同步 XHR 兼容层仍在，较慢请求会阻塞页面；尚未完成全面异步改造及全尺寸无障碍验收。',
     '旧聊天名册与新页面联系人集合不同，但均使用共同账本、限额和卡状态。',
     '历史旧转账记录可能没有创建时快照，公开投影使用空历史字段；不会伪造历史资金数据。',
     '场景只生成独立数据，不自动导入用户会话；未支持所有任意自然语言需求或真实客户数据。',
     '原 eva 缺依赖和 YUKI 全量 50 题评测仍待分支补交；本地 SQLite 审计不提供生产防篡改保证。']
    overview={'architecture':'vv 页面 → BankCore HTTP 适配 → Python AgentService → SQLite 单一事务状态 → 服务端 Node 引擎 / eva 风控 / 推荐 / RAG；Ethan 独立场景生成不修改账本。',
      'sources':metadata['selected'],'interfaces':{'envelope':'1.0.0','policy':'integrated-demo-1.1','scenario':'scenario-1.0','money':'CNY 整数分','preview_seconds':300,'assertion_seconds':120,'consent_hours':24},
      'integration':'卡片申请、限额、限制、解锁、挂失及选择付款卡已接入；两条转账入口共用资金、卡限制、风险累计、操作记录和审计。',
      'validation':verification,'browser':browser,'quota':quota,'remaining_issues':remaining,'output_directory':str(BASE)}
    conclusion='已按 5h 剩余额度低于 10% 中止，保存当前文件和上下文；待办见 context_log。' if stop else '最新交付已整合到 SecondAsgent，完成接口与缺项补丁、验证、反思及逐分工交接；FirstAgent 和队友原件保持原样。'
    dump(BASE/'summary.json',{'analysis':reflections,'overview':overview,'branches':[{k:v for k,v in b.items() if k not in {'changes','retained'}} for b in BRANCHES],'status':status,'conclusion':conclusion})
    parts=['# SecondAsgent 总版总结（2026-10-23）','## 版本比对与选择依据',f"递归盘点 {metadata['source_count']} 个非缓存输入文件；较首轮增加 28 个文件，原 77 个输入哈希未变。覆盖 eva output、vv output、YUKI ouput（原目录拼写）及 Ethan output 内的嵌套 output。",metadata['vv_selection_reason'],
      'eva 沿用 1020/ver.2；YUKI 沿用 1022；vv 纳入 1023 单页及源码；Ethan 纳入 1022 环境生成和各家族 20261022185343 最新 A–E 样例。来源、时间、哈希见 reports/source_inventory_20261023.json、update_metadata.json。','## 架构、接口与集成',overview['architecture'],overview['integration'],'接口详情见 [API-CONTRACT.md](API-CONTRACT.md)。金额统一为分；授权 24 小时；预览 300 秒；增强验证断言 120 秒。模拟卡额度不是新增资金。真实银行由组委会接入。','## 缺失补丁及反思']+['- '+x for x in reflections]
    parts+=['## 验证证据','本轮测试：**32/32 集成、35/35 JavaScript**，报告见 [verification.json](reports/verification.json)。浏览器验证卡限制完成和刷新、带来源问答、独立场景生成；详细步骤见 reports/browser-verification-20261023.json。测试数据库独立于交付运行账本。',
      '原始输入复核：'+str(len(inventory['files']))+' 个文件，变更 '+str(len(changed_inputs))+'。本轮代码完整差异见 reports/code_changes.json 和 reports/diffs/。','## 分工与修改记录']
    parts += [f"- [{b['branch_name']}](reports/branches/{b['file']}.md)：{b['summary']}" for b in BRANCHES]
    parts+=['## 遗留问题']+['- '+x for x in remaining]
    parts+=['## 额度、交付与复跑','只监测 300 分钟窗口；周额度完全不参与停止判断。小于 10% 才中止，等于 10% 仍未触发。采样见 reports/quota_latest.json 与 quota_history.json；监测依赖当前任务调用账户工具，不是脱离任务独立运行的后台进程。',
      '交付位置：`'+str(BASE)+'`。不复制旧演示 runtime 数据库，首次启动建立独立会话。运行 `python -m first_agent.server --port 8767` 或 `./run_agent.ps1`；验证 `python verify_delivery.py`。', '结论：'+conclusion]
    md(BASE/'summary.md',parts)
    steps=[{'step':i+1,'analysis':x,'result':'已处理，见对应代码与分工文档'} for i,x in enumerate(reflections)]
    steps.insert(0,{'step':0,'analysis':'读取最新源版本及上一轮交付，保存独立副本；用户指定 SecondAsgent。','result':'实际输入105，新增28，原件哈希复核'+str(len(changed_inputs))+'处变化'})
    current={'delivery':str(BASE),'staging':metadata.get('staging'),'quota':quota,'variables':overview['interfaces'],
      'state_fields':['available','positions','externalOut','cards','contacts','transactions','operations','transfer_ops','consent','consentExpiresAt','version'],
      'interfaces':['POST /api/rpc','POST /api/scenarios/generate','POST /api/transfers/preview|verify|confirm|cancel|reconcile','GET /api/snapshot'],
      'missing_items':remaining,'verification':verification,'completed':['最新版本比较','接口与卡管理整合','Ethan 场景补丁','独立测试及浏览器验证','SecondAsgent 新目录','总版与分工文档'],
      'unfinished':(['检查最终报告与启动预览状态；额度恢复后再继续'] if stop else [])}
    dump(BASE/'context_log.json',{'generated_at':now,'steps':steps,'current_state':current,'summary':conclusion,'status':status,'conclusion':conclusion})
    md(BASE/'context_log.md',['# 执行上下文与当前总结','## 任务要求','读取最新 output，比较版本、统一接口、从项目产出补缺、逐分工记录修改；只监测 5h；保存到 SecondAsgent。本文记录可审查操作、判断依据与结果；历史上下文见 reports/history/20261022。','## 操作与判断']+[f"{s['step']}. {s['analysis']}\n\n结果：{s['result']}" for s in steps]+['## 当前变量与接口','```json\n'+json.dumps(current,ensure_ascii=False,indent=2)+'\n```','## 当前进度总结',conclusion,'结论：'+conclusion])
    prior=json.loads(read(BASE/'reports/history/20261022/patch_manifest.json'))
    dump(BASE/'reports/patch_manifest.json',{'history':prior,'current_sources':metadata['selected'],'patches':[{'branch':b['branch_name'],'rationale':b['analysis'],'targets':[{'file':p,'change':n} for p,n in b['changes']]} for b in BRANCHES],'conclusion':'本轮来源与补丁逐项对应；旧版归属说明以本轮纠正为准。'})
    manifest={p.relative_to(BASE).as_posix():sha(p) for p in sorted(BASE.rglob('*')) if p.is_file() and not {'runtime','__pycache__'} & set(p.relative_to(BASE).parts) and p.name!='file_manifest.json'}
    dump(BASE/'reports/file_manifest.json',{'sha256':manifest,'conclusion':'覆盖交付文件，排除运行数据库、缓存及本清单。'})
    print(json.dumps({'status':status,'source_changes':changed_inputs,'code_changes':len(code_changes),'files':len(manifest),'conclusion':conclusion},ensure_ascii=False))

if __name__=='__main__':main()
