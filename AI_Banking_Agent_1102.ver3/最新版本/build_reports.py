"""Publish current integration notes without rewriting historical evidence."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import difflib, hashlib, json, shutil

ROOT=Path(__file__).resolve().parent

def write(path,text):
    target=ROOT/path;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(text.rstrip()+'\n',encoding='utf-8')

def dump(path,data):write(path,json.dumps(data,ensure_ascii=False,indent=2))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def publish_research_addendum():
    """Keep optional research handoffs visible when integration notes regenerate."""
    context_path=ROOT/'research/macro_quant/context.json'
    if not context_path.exists():
        return
    research=json.loads(context_path.read_text(encoding='utf-8'))
    start='<!-- macro-quant-research:start -->'
    end='<!-- macro-quant-research:end -->'
    block=(start+'\n## 宏观量化研究增量（2026-10-24）\n\n'
           '新增独立离线模块 [建模说明](research/macro_quant/项目目标与思路.md)、'
           '[参数与字段](research/macro_quant/params.json)、'
           '[核心代码](research/macro_quant/quant_recommender.py)。'
           '采用共同期限情景、宏观条件概率和均值/CVaR评分；'
           '原偏好推荐、预算回退、业务账本及审批规则保持不变。\n\n'
           '接口新增的是 [离线契约](research/macro_quant/INTERFACE.md)，没有新增HTTP路由。'
           '真实数据尚未接入，合成验证不代表市场有效性。'
           '本增量状态与证据分别见 [接续记录](research/macro_quant/context.json) 和 '
           '[验证报告](research/macro_quant/verification.json)；不并入此前整合测试计数。\n'+end)
    for name in ('README.md','API-CONTRACT.md','context_log.md','summary.md'):
        path=ROOT/name
        if not path.exists():
            continue
        content=path.read_text(encoding='utf-8')
        if start in content and end in content:
            left=content.index(start);right=content.index(end,left)+len(end)
            content=content[:left]+block+content[right:]
        else:
            content=content.rstrip()+'\n\n'+block+'\n'
        write(name,content)
    for name in ('context_log.json','summary.json'):
        path=ROOT/name
        if path.exists():
            content=json.loads(path.read_text(encoding='utf-8'))
            content.setdefault('research_modules',{})['macro_quant']=research
            dump(name,content)

def main():
    verification=json.loads((ROOT/'reports/verification.json').read_text(encoding='utf-8'))
    inputs=json.loads((ROOT/'reports/source_inventory_20261024.json').read_text(encoding='utf-8'))
    originals=[];changes=[]
    for row in inputs:
        source=Path(row['source']);target=ROOT/row['target']
        originals.append({'path':str(source),'unchanged':source.exists() and sha(source)==row['sha256']})
        if target.exists() and sha(target)!=row['sha256']:
            change={'file':row['target'],'source':str(source),'before_sha256':row['sha256'],'after_sha256':sha(target)}
            if source.exists() and target.suffix in {'.py','.js','.md','.ps1'}:
                diff=''.join(difflib.unified_diff(source.read_text(encoding='utf-8-sig').splitlines(True),target.read_text(encoding='utf-8-sig').splitlines(True),fromfile=str(source),tofile=row['target']))
                name=row['target'].replace('/','__').replace('\\','__')+'.diff'
                write(Path('reports/diffs_20261024')/name,diff)
                change['diff']='reports/diffs_20261024/'+name
            changes.append(change)
    dump('reports/source_integrity.json',{'files_checked':len(originals),'changed':[r for r in originals if not r['unchanged']],
        'module_python_unchanged':all(sha(ROOT/r['target'])==r['sha256'] for r in inputs if r['target'].startswith('modules/') and r['target'].endswith('.py'))})
    dump('reports/code_changes_20261024.json',changes)
    now=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    counts=verification['integration'];checks=verification.get('module_checks',{})
    evidence=f"整合测试 {counts['passed']}/{counts['run']}；JS 规则 {verification['vv_engine']['passed']}/35"
    if checks:
        evidence+=f"；分析 {checks['analysis']['test_count']} 项；环境生成 {checks['environment']['test_count']} 项"
    limitations=[
        '规则驱动、本地模拟；没有接入开放式大模型或真实 MFA。真实银行由组委会本地部署接入，沿用已确认交付边界。',
        '真实脱敏流水未提供，未做真实数据校准；同源评测不是现实准确率。',
        '会话仍是月度汇总样本，无逐笔重复扣款依据、信用卡明细、家庭生日及活动日历。会话卡片直接投影当前持久化状态，缺失账单不编造。',
        '生成的 A–G 与会话账本独立；F 的生日锁定仅为合成场景预测，不改变会话资金。',
        '推荐是偏好排序；分析上限为零保留配置并警告，不能解释为可投资建议；执行仍独立走原审批链。',
        'SQLite 幂等和审计限单机；不声称分布式事务、生产防篡改或生产认证。',
        '同步 XHR、原有两套虚构联系人名册继续保留；未进行全尺寸与无障碍全面验收。',
        '农历节日仅 2026–2027 演示对照表；未拆分上游 scenario_generator.py，保持已验证算法源码。',
        '兜底 ethan_fallback_toolkit 保持独立；它的 scenario-1.1 不与 Ethan 的 1.0.0 混用，不接入第二套现金流算法。',
        '原 eva 完整依赖与 YUKI 全量 50 题评测仍按历史边界处理，本轮未宣称补齐。',
    ]
    decisions=[
        ('运行基线','SecondAsgent 为完整执行基线，新增代码只落在 Third_Agent。Ethan 的 FirstAgent 参考是接入材料，不能覆盖新版卡管理。'),
        ('推荐金额','读取 organizer 的 recommendation 视图；最终金额再取 min(视图预算, 原引擎 capacity, 当前配置)。分析上限为零沿用配置/引擎约束，并保留应急金提示；缺 read 或模块不可用时回退旧规则。'),
        ('卡管理','复用原卡预览/验证/确认/审核/回执。analysis_bridge 投影当前卡状态、限额、当日已用；不把信用卡额度当成存款，不伪造信用卡账单。'),
        ('界面数据','实时资金、授权、操作状态继续使用 /api/snapshot；display 只供只读分析，不覆盖 UI 账本。Agent 面板增加分析和整理按钮，生成按钮显式用 contract 格式。'),
        ('整理入口','新增 data.organize，纳入 /api/analysis 会话工具白名单；仅服务端派生上下文、只读、有 read 授权。CLI/纯函数继续可用。'),
        ('生成契约','新 A–G 生成走 Ethan 唯一 scenario_adapter；prompt 或 format=contract 返回新契约。requirement 无 format 保留旧 scenario-1.0 投影，签名金额不同，不能互相猜测。'),
        ('接入路径','first_agent/analysis_bridge.py 在新交付包中为共享接入基线；模块位于 modules/，默认不再依赖队友 Desktop 路径。环境变量 AI_BANKING_ANALYSIS_DIR 仍支持成对模块的替换。'),
        ('知识模块','客户账本和整理视图不进入 RAG；沿用八篇知识原文、BM25 与证据引用。'),
        ('待真实数据','没有用户提供的脱敏数据，不能宣称校准完成；保留为明确外部依赖，不用合成数据冒充真实数据。'),
    ]
    context_files=[
        '../AI_Banking_赛题对照与方向校准_2026-10-19.md','../FirstAgent/context_log.md','../SecondAsgent/context_log.md',
        '../SecondAsgent/reports/branches/Ethan.md','../ethan_fallback_toolkit/context_log.md','../ethan_fallback_toolkit/handoff/integration.md',
        'sources/Ethan_1024/主任务_任务进度与数据_2026-10-24.md','sources/Ethan_1024/主任务_任务进度与数据_2026-10-24.json',
        'sources/Ethan_1024/AI_Banking_环境生成_逻辑链与交接.md','sources/Ethan_1024/数据整理Agent_逻辑链与接口.md',
        'modules/环境生成agent/AI_Banking_项目进度.md','modules/环境生成agent/AI_Banking_上下文与进度.json',
    ]
    context={'updated_at':now,'status':verification['conclusion'],'delivery':str(ROOT),'basis':'SecondAsgent + Ethan 1024 ver.1',
             'context_references':context_files,'decisions':[{'topic':k,'decision':v} for k,v in decisions],
             'verification':verification,'known_boundaries':limitations,
             'source_integrity':'reports/source_integrity.json','api_contract':'API-CONTRACT.md',
             'steps':[
                 '通读历史上下文、当前交接及实际代码，识别 FirstAgent 与 SecondAsgent 版本差异。',
                 '复制完整执行基线并保存来源哈希；排除原运行数据库，保留原交付目录。',
                 '复跑未改动的分析 115、环境 73、核心执行 20 项基线；受限临时目录失败后经授权复跑通过。',
                 '适配会话、分析/整理路由、推荐消费、场景兼容及页面按钮；所有算法模块 Python 保持来源字节一致。',
                 '初次回归发现旧聊天多工具数量从 2 变 3；将分析结果替代旧账单查询，保持旧测试原断言不变。',
                 '执行完整回归、预算回测和 800/1200 元演示；生成接口、总版、分工、差异与上下文。',
             ]}
    dump('context_log.json',context)
    text='# Third_Agent 执行上下文与接续记录\n\n更新：'+now+'。当前验证状态：'+verification['conclusion']+'。\n\n'
    text+='## 开发路径核对\n\n'+'\n'.join(f'{i+1}. {step}' for i,step in enumerate(context['steps']))+'\n\n'
    text+='## 上下文优先级\n\n源记录完整保留。FirstAgent “卡操作未实现”是旧版本事实；SecondAsgent 已验证的卡操作优先。Ethan “不存在 scenarios.py”仅适用于其接入仓库，本地 SecondAsgent 确有该旧文件。Third_Agent 公共生成已改用最新 adapter，旧文件只供历史兼容测试。历史额度和中止记录不作为本次测试证据。\n\n'
    text+='## 本轮决策\n\n'+'\n\n'.join(f'### {k}\n\n{v}' for k,v in decisions)+'\n\n'
    text+='## 已读上下文\n\n'+'\n'.join('- `'+p+'`' for p in context_files)+'\n\n'
    text+='## 当前证据与限制\n\n'+evidence+'。完整证据见 reports/verification.json。\n\n'+'\n'.join('- '+s for s in limitations)
    write('context_log.md',text)
    write('INTEGRATION-DECISIONS.md','# 跨板块整合决议\n\n'+ '\n\n'.join('## '+k+'\n\n'+v for k,v in decisions)+
          '\n\n以上为本轮集成实现选择，不冒称队友已逐人确认。未向队友或外部服务发消息。\n\n'+evidence+'。')
    write('README.md',f'''# AI Banking · Third_Agent

以 SecondAsgent 的执行链整合 Ethan 2026-10-24 ver.1 的环境生成、金融分析和数据整理。原目录保留；全部金融行为为本地模拟。

## 启动

需要 Python 3.11+、Node.js 18+；仅标准库，无需安装新依赖。

```powershell
cd F:\\AI_Banking\\Third_Agent
python -m first_agent.server --port 8768
# 或 .\\run_agent.ps1
```

打开 http://127.0.0.1:8768/ 。首次启动建立本目录 runtime/agent.sqlite3；不会迁移或覆盖旧会话。Ctrl+C 停止。

在 Agent 面板开启查询权限后，可输入“分析账单并检查订阅”“查看现金流”“预算建议”“整理数据”。转账、订阅和卡管理继续使用原预览、验证、确认、回执流程。演示验证码 246810。生成场景按钮只生成独立 A–G 数据。

## 验证与演示

```powershell
python verify_delivery.py
python demo_full_chain.py
python demo_full_chain.py --amount-minor 120000
python build_reports.py
```

`verify_delivery.py` 在临时数据库中复跑整合、JS、分析、生成、1092 次预算组合、黄色/红色全链路演示。`build_reports.py` 根据已有验证生成当前交接；旧文档生成器入口已指向它，避免把文档恢复成旧版本。

本轮证据：{evidence}。最终状态：{verification['conclusion']}。详细日志在 reports/。

## 文件入口

- `first_agent/`：单一会话账本、执行控制和只读分析桥；Python 包名保留 first_agent。
- `modules/主任务_金融分析与量化/`：Ethan 分析、organizer 和回测源码；算法原样复用。
- `modules/环境生成agent/`：Ethan A–G 生成、双层校验、唯一契约适配与 SQLite 幂等。
- `web/`：原页面及新增分析、整理、A–G 生成入口。
- [统一接口](API-CONTRACT.md)、[整合决议](INTEGRATION-DECISIONS.md)、[总版总结](summary.md)、[上下文](context_log.md)。
- `reports/branches/`：Ethan、eva、vv、YUKI 与集成分工交接；`reports/history/` 保留历史。
- `sources/`：参考快照；不是运行入口。

## 边界

'''+ '\n'.join('- '+s for s in limitations))
    summary={'updated_at':now,'delivery':str(ROOT),'status':verification['conclusion'],'verification':verification,
             'integrated':['会话只读分析','四视图整理','预算推荐衔接','A–G 新旧契约兼容','原卡管理/转账/订阅执行链保留'],
             'limitations':limitations,'source_integrity':'reports/source_integrity.json'}
    dump('summary.json',summary)
    write('summary.md',f'''# Third_Agent 整合总结

更新：{now}。完成本轮可在本地交付范围内的跨模块整合。{evidence}；状态 {verification['conclusion']}。

## 结果

- 保留 SecondAsgent 的卡管理、转账日累计、确认绑定、未知查单、幂等和统一资金账本。
- 接入 Ethan A–G 环境、账单/异常/订阅/现金流/流动性/预算，以及 organizer 四视图。
- 新增 `GET/POST /api/analysis`、`GET /api/analysis/status`；对客禁止评测开关和本地文件路径。
- 推荐直接消费整理视图，仍受原配置与引擎资金上限约束；零上限提示和缺模块回退沿用已验证规则。
- 生成接口保留旧 requirement 请求兼容，新增 prompt/contract 请求；独立场景不导入会话。
- 更新根接口、上下文和分工说明，修正跨版本“卡未实现”等适用范围；上游原文留档。

## 可追溯证据

- `reports/verification.json` 与逐项日志：本次真实执行结果，不沿用队友测试计数作当前证明。
- `reports/budget_backtest.json`：本次重跑的 1092 次预算组合及确定性检查。
- `reports/source_inventory_20261024.json`、`reports/source_integrity.json`：来源 SHA-256 与原件未改核对。
- `reports/code_changes_20261024.json`、`reports/diffs_20261024/`：本轮逐文件变化。
- `INTEGRATION-DECISIONS.md`：对 Ethan 交接中六项协作问题的具体实现决策。

## 后续边界

'''+ '\n'.join('- '+s for s in limitations))
    base=(ROOT/'reports/history/20261023/API-CONTRACT.md').read_text(encoding='utf-8')
    base=base.replace('# SecondAsgent 统一接口','# Third_Agent 统一接口')
    start=base.index('## 独立场景生成');end=base.index('## 接入分工',start)
    base=base[:start]+SCENARIO_CONTRACT+'\n\n'+base[end:]
    base=base.replace('ready, persistent, mode |','ready, persistent, mode, analysis.available |')
    write('API-CONTRACT.md',base+'\n\n'+ANALYSIS_CONTRACT)
    branches={
        'Ethan':('环境、分析与数据整理',[
            '`modules/环境生成agent/*.py`、`modules/主任务_金融分析与量化/**/*.py`：按实际交付复制，Python 算法未修改，保留 73/115 项回归。',
            '`first_agent/analysis_bridge.py`：在交付参考基础上改为本包路径；会话卡片投影；按 signed amount 重建对账期初；独立区分转账/申购/赎回与消费；注册 data.organize；拒绝文件/评测/客户端数据参数。',
            '`first_agent/service.py`：场景转发唯一 adapter；legacy 只是输出投影；推荐消费 organizer 的 recommendation 视图，最终再受配置/引擎限额约束。',
            '`demo_full_chain.py`：原演示只修改依赖路径，黄色/红色档分别复跑。',
            '`tests/test_analysis_integration.py`：保留 14 项参考测试；正上限用例改为模拟整理视图；场景断言对齐本地 flat data 响应，不改原账单数值断言。',
        ]),
        'eva':('执行与风控',[
            '`first_agent/service.py` 原转账、卡、确认、累计、查单、SQLite 事务逻辑保留；增加分析/生成 dispatch 与推荐衔接。',
            '`web/journey-engine.js`、`first_agent/vendor/eva/`、`first_agent/engine_worker.cjs`：原样复用；卡管理已在本地 SecondAsgent 实现，不被早期 FirstAgent 文档覆盖。',
            '整理的 cards 视图为数据读取；仍从本地持久化 cards 读取实际状态，不创建新账户、不把额度加到账户。',
        ]),
        'vv':('界面与只读显示',[
            '`web/agent-panel.js`：生成按钮显式 contract 请求，新增现金流/预算与数据整理按钮和中文只读摘要；输出使用 textContent。',
            '`web/journey-workspace.js`：只更新已过期的账单/提醒/生日能力说明；`web/journey-engine.js`、`web/server-bridge.js` 原样复用。',
            '实时显示继续 /api/snapshot；display 不保存授权、操作状态，不替换原快照。',
        ]),
        'YUKI':('知识与评测',[
            '`knowledge/` 与 `first_agent/vendor/rag/` 原样复用；不向 RAG 发送客户账本或 organizer 包。',
            '对客分析只接受 days/month/year 的工具参数；scenario_file、include_evaluation、客户端 scenario/context 均拒绝。',
            '生成接口剥离 expected_insights，评测只在离线模块中运行；同源评测结果不等于真实准确率。',
        ]),
        'integration':('集成与交付',[
            '`first_agent/server.py`：新增 GET/POST 分析及状态路由、健康分析自检，默认端口 8768；原金融路由保留。',
            '`tests/test_third_agent.py`：13 项跨模块回归，覆盖权限、只读、卡状态、推荐实际正上限、A–G、幂等和 HTTP 会话隔离。',
            '`verify_delivery.py`：复跑所有模块、JS、预算回测和两种转账演示；各模块独立进程，避免通用模块名冲突。',
            '`build_reports.py`、README/API/summary/context/分工：根据本次证据同步生成。旧 write_reports/write_update_reports 入口指向新生成器；旧版本留 reports/history。',
        ]),
    }
    for name,(role,lines) in branches.items():
        old=ROOT/'reports/branches'/f'{name}.md';archive=ROOT/'reports/history/20261023/branches'/f'{name}.md'
        if old.exists() and not archive.exists():archive.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old,archive)
        write(Path('reports/branches')/f'{name}.md',f'# {name}｜Third_Agent 分工交接\n\n模块：{role}。更新：{now}。\n\n## 逐文件修改与复用\n\n'+
              '\n\n'.join('- '+line for line in lines)+'\n\n## 验证与接续\n\n'+evidence+'；完整证据以本轮 reports/verification.json 为准。\n\n参见 ../../API-CONTRACT.md、../../INTEGRATION-DECISIONS.md 和 ../code_changes_20261024.json。\n\n历史交接完整保留在 ../history/20261023/branches/，后续只追加或更新当前版本，勿运行历史脚本覆盖本轮。')
    publish_research_addendum()
    # Recompute after publishing so recorded digests describe the final files.
    final_changes=[]
    tracked=set()
    for row in inputs:
        source=Path(row['source']);target=ROOT/row['target'];tracked.add(row['target'])
        if target.is_file() and sha(target)!=row['sha256']:
            record={'file':row['target'],'status':'modified','source':str(source),
                    'before_sha256':row['sha256'],'after_sha256':sha(target)}
            if source.exists() and target.suffix in {'.py','.js','.md','.ps1'}:
                name=row['target'].replace('/','__').replace('\\','__')+'.diff'
                diff=''.join(difflib.unified_diff(source.read_text(encoding='utf-8-sig').splitlines(True),target.read_text(encoding='utf-8-sig').splitlines(True),fromfile=str(source),tofile=row['target']))
                write(Path('reports/diffs_20261024')/name,diff);record['diff']='reports/diffs_20261024/'+name
            final_changes.append(record)
    additions={'first_agent/analysis_bridge.py':'sources/Ethan_1024/FirstAgent_分析接入/analysis_bridge.py',
               'tests/test_analysis_integration.py':'sources/Ethan_1024/FirstAgent_分析接入/tests/test_analysis_integration.py',
               'demo_full_chain.py':'sources/Ethan_1024/demo_full_chain.py',
               'tests/test_third_agent.py':None,'build_reports.py':None,'INTEGRATION-DECISIONS.md':None}
    for name,reference in additions.items():
        record={'file':name,'status':'adapted_reference' if reference else 'added','after_sha256':sha(ROOT/name)}
        if reference:
            record['reference']=reference
            diff=''.join(difflib.unified_diff((ROOT/reference).read_text(encoding='utf-8-sig').splitlines(True),(ROOT/name).read_text(encoding='utf-8').splitlines(True),fromfile=reference,tofile=name))
            diff_name=name.replace('/','__')+'.diff';write(Path('reports/diffs_20261024')/diff_name,diff)
            record['diff']='reports/diffs_20261024/'+diff_name
        final_changes.append(record)
    dump('reports/code_changes_20261024.json',final_changes)
    print(json.dumps({'status':verification['conclusion'],'evidence':evidence,'source_files':len(originals),'originals_changed':sum(not r['unchanged'] for r in originals)},ensure_ascii=False))


SCENARIO_CONTRACT='''## 独立场景生成（Third_Agent 增量）

`POST /api/scenarios/generate` 需要本机会话和 Idempotency-Key，无需金融写权限。全部 A–G 通过本包 `modules/环境生成agent/scenario_adapter.py` 生成并双层校验；不写会话账本。

| 请求 | 返回 data | 金额语义 |
|---|---|---|
| `{ "requirement": "普通银行用户" }` | 兼容 `schema_version:"scenario-1.0"`，顶层无 user | transactions.amount_minor **带符号**；id 为旧字段 |
| `{ "prompt": "配偶生日锁定1000元", "seed":42, "reference_date":"2026-10-23" }` | 完整 `schema_version:"1.0.0"`，A–G 分析契约 | amount_minor **绝对值**，amount 带符号，transaction_id、direction、transaction_type |
| `{ "requirement":"信用卡", "format":"contract", "scenario_type":"G" }` | 同完整契约 | 同上 |

`format` 为 legacy/contract；有 prompt 时默认 contract，否则默认 legacy。prompt 和 requirement 同时给且不一致时拒绝。可选 scenario_type 为 A–G，seed 为 0 到 2^32-1 整数，reference_date 为真实存在的 YYYY-MM-DD；严格拒绝布尔 seed。用户输入 1–2000 字符。不支持的需求返回 SCENARIO_UNSUPPORTED；旧 legacy 保留 SCENARIO_INVALID。其余参数错误 INVALID_ARGUMENT。

对客接口拒绝 include_evaluation 和未知参数；输出不含 expected_insights/evaluation_only_fields。返回恒 simulated=true、ledger_modified=false。生成数据含脱敏卡片、账单、家庭/日历及场景专项块，缺块不编造。卡账单独立于存款，booked 才参与余额。

同会话相同 Idempotency-Key 原请求重放由主服务 requests 表持久化，改参复用报冲突。上游另有独立单机 SQLite 生成缓存；两者均不提供分布式保证。legacy 只是完整契约的兼容输出，不喂给分析 loader，也不是兜底 toolkit 的 scenario-1.1。
'''

ANALYSIS_CONTRACT='''## 只读分析与数据整理（接口文档增量 2026-10-24）

响应 envelope 和执行策略仍为 1.0.0 / integrated-demo-1.1；本节为向后兼容的新增 API。默认启动端口 8768。

| Method | Path | 请求/返回 | 权限 |
|---|---|---|---|
| GET | /api/analysis/status | available、tools、error | 已建会话；不读客户数据 |
| GET | /api/analysis?tool=bills.summary&month=2026-10 | data.tool/source/result/simulated/ledger_modified | consent.read 且未过期 |
| POST | /api/analysis | `{ "tool":"data.organize", "args":{ "days":30 } }` | consent.read；必须 Idempotency-Key |
| GET | /api/health | 新增 data.analysis.available | 仅可用性，不返回账本 |

会话工具：bills.summary、bills.categories、anomalies.detect、subscriptions.burden、cashflow.project、liquidity.available、budget.advice、analysis.pipeline、data.organize。默认 analysis.pipeline；scenario.generate 不能走会话分析入口。

参数沿用工具规范：账单 month/year；现金流/流动性 days；预算 days/month；pipeline days/month；organize 只接受 days；days 为 1–366 整数。GET 的数字字符串在桥内转整数。无参数的工具拒绝额外参数。所有会话工具拒绝 scenario_file、include_evaluation、data、context 等客户端数据/路径/标准答案参数，身份和账本均从 cookie 对应会话读取。

成功 data 为 `{tool,source:"session_ledger",result,simulated:true,ledger_modified:false}`。未知工具 TOOL_NOT_REGISTERED，参数错误 INVALID_ARGUMENT，缺 read 为 SCOPE_DENIED，授权过期 SCOPE_EXPIRED，模块不可用 ANALYSIS_UNAVAILABLE；失败不改金融状态。读取仍记录审计/幂等日志，ledger_modified=false 专指业务账本。

`data.organize` 的 result 含 views.analysis/recommendation/cards/display 与 manifest；分析金额为整数分，只有 recommendation.profile.budget_cny 为 CNY 元。上游个别带符号 amount 仍以分计，不能仅根据字段后缀猜单位。manifest 显示缺失数据，display 始终是派生只读摘要。对客不开放评测开关，离线 organizer 的显式评测能力仍保留。

会话 cards 使用 card_id/card_type/masked_card_number/status/transaction_limit_minor/spent_today_minor/source。无信用卡账单和事件时分别列入 missing；不会从额度推算欠款。initial_balance_minor 为当前余额减已记账流水的重建期初，不冒称原银行记录的期初。申购/赎回标为 investment_purchase/investment_redemption，不作为消费/退款。

### 推荐金额与来源

`GET /api/products` 与 `POST /api/recommendations` 新增 budget_basis：configured_minor、engine_capacity_minor、analysis_headroom_minor（未授权/不可用为 null）、applied_minor、source、analysis_status。

- 有有效 read 且整理可用：消费 organizer 的 recommendation 视图。最终 `applied_minor=min(state.amount, engine.capacity, view.conditions.budget_minor)`。
- 上游视图按已验证规则：正分析上限与配置取 min；零上限保留配置并给应急金提示。因此 source 仍可为 engine_capacity，同时 analysis_headroom_minor=0。
- 缺 read 或模块不可用：沿用旧配置/引擎容量；source=engine_capacity，analysis_status=not_authorized/unavailable；不会自动授予 read。
- 正上限实际收紧时 source=analysis；可用时 analysis_status=available。预算视图是草稿，产品推荐与最终执行仍受原引擎规则约束。

实时资金与操作继续以 /api/snapshot 和原金融回执为准。新整理和生成数据不导入会话，不改变 consent/version/操作状态，不让客户账本进入 RAG。
'''

if __name__=='__main__':main()
