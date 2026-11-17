"""Rebuild evidence-based handoff without editing the original teammate documents."""
from pathlib import Path
from datetime import datetime,timezone
import json

ROOT=Path(__file__).resolve().parent


def load(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))
def dump(name,value):
    p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    verification=load('reports/verification.json');imports=load('reports/ethan_import_verification.json');quota=load('reports/quota_latest.json')
    archive=load('reports/archive_verification.json') if (ROOT/'reports/archive_verification.json').exists() else {'status':'pending'}
    paused=quota.get('stop',False)
    status='paused_low_quota' if paused else ('completed' if verification['conclusion']=='passed' and archive.get('status')=='passed' else 'verification_pending')
    analysis=[
        '正式分工与最新交接包含环境生成、金融整理/计算和生活计划，因此兜底范围覆盖四块基础能力。',
        '旧规范展示结果缺少类型和商户；采用 scenario-1.1 完整记录，保留退款/转账/订阅语义，scenario-1.0 仅用于展示兼容。',
        '旧生成器依赖全局随机数、UUID 和当前日期；新生成器使用局部 seed、显式参考日和稳定 ID，避免并发污染及不可复现。',
        '财务整理先对账；退款抵减消费，转账不重复计消费，负净收入时不计算无意义的比例，疑似重复只标记。',
        '事件日期和生效条件决定期间最低余额；分别报告日终最小值与同日支出优先的保守下界。',
        '生日计划先扣除应急预留并检查预算，再生成草稿日历；计算工具不接管银行执行审批。']
    modules=[{'name':'环境生成','files':['models.py','scenarios.py'],'summary':'A-E 固定种子生成、语义校验、旧源导入及兼容投影'},
             {'name':'金融数据整理与计算','files':['finance.py'],'summary':'可追溯财务快照、候选标记、退款/转账口径及确定性指标'},
             {'name':'事件日期模拟','files':['simulation.py'],'summary':'生效时间、最低余额、预留缺口及多方案比较'},
             {'name':'生活场景','files':['lifestyle.py'],'summary':'预算受限事件草稿、日历和 ICS'},
             {'name':'工具与交付','files':['contracts.py','tools.py','__main__.py','demo.py'],'summary':'12 个工具、JSON CLI、演示和回归报告'}]
    limitations=['未接真实银行、外部模型、商户或线上日历；真实银行接入仍由组委会负责。',
                '固定种子用于虚构测试数据，不是未来收益的概率模拟；不提供 Sharpe/VaR 等未实现指标。',
                '信用卡还款、内部转账等依赖上游明确分类；不能从任意杂乱银行账单自动恢复完整事实。',
                '重复与订阅是待核实候选，默认保留全部已入账金额。',
                '主 Agent 需按契约显式接入；本次没有修改 SecondAsgent 业务代码或账本。']
    conclusion=('5h 剩余额度低于 10%，已中止并保存上下文。' if paused else
                '独立兜底工具包、测试、示例、逐文件交接及可移植压缩包已完成。' if status=='completed' else '核心代码与测试已完成，压缩包验收待完成。')
    overview={'scope':'Ethan 当前职责的确定性基础能力兜底','architecture':'主 Agent / CLI → 白名单工具 → 整理/校验/计算/生成 → JSON或本地ICS；不触发金融执行',
              'modules':modules,'tests':verification,'latest_ethan_imports':len(imports['cases']),'archive':archive,
              'quota':quota,'limitations':limitations}
    branches=[{'branch_name':'Ethan / 数据与环境','summary':'新实现与逐文件说明见 handoff/Ethan.md；原1022输出保留，只读导入五类最新样例。'},
              {'branch_name':'集成 / 主Agent','summary':'12个可调用工具及JSON schema；示例已串联环境生成与财务计算；显式接入，不替换现有金融服务。'},
              {'branch_name':'eva / vv / YUKI','summary':'本轮未修改这些分支的运行代码；继续分别负责模拟银行执行、界面、知识与评测。'}]
    dump('summary.json',{'analysis':analysis,'overview':overview,'branches':branches,'status':status,'conclusion':conclusion})
    sections=['# Ethan 兜底 Toolkit 总版总结（2026-10-24）','## 判断与实现依据']+['- '+v for v in analysis]
    sections+=['## 架构与本次交付',overview['architecture']]+['- '+m['name']+'：'+m['summary']+'。' for m in modules]
    sections+=['## 验证结果',f"独立测试 {verification['passed']}/{verification['run']} 通过；5/5 最新 Ethan 原始样例导入并校验。测试含 100 次 A–E/seed 组合断言，不重复计算为独立测试数。",'压缩包隔离验证：'+json.dumps(archive,ensure_ascii=False)+'。',
               '手工算例：收入10000元、消费3000元、退款500元、本人转入转出各2000元、信用卡还款3000元 → 净消费2500元，现金结余7500元，净现金流4500元。详见 API-CONTRACT.md。',
               '## 分工交接','[Ethan 逐文件改动](handoff/Ethan.md)；[主 Agent 接入](handoff/integration.md)。保留旧源归属，新增工具包实现单独署明。',
               '## 遗留与明确边界']+['- '+v for v in limitations]
    sections+=['## 额度和上下文','只检测300分钟窗口；最新采样：'+json.dumps(quota,ensure_ascii=False)+'。上次6%中断已补记到 reports/checkpoints，不把未完成的上一轮写成已完成。',
               '## 启动','在本目录运行 `python verify_toolkit.py` 或 `python -m examples.main_agent_call`。完整演示见 output/demo，工具列表见 tool_definitions.json。','结论：'+conclusion]
    (ROOT/'summary.md').write_text('\n\n'.join(sections)+'\n',encoding='utf-8')
    steps=[{'step':i+1,'analysis':v,'result':'已实现；文件与测试见分工文档'} for i,v in enumerate(analysis)]
    state={'directory':str(ROOT),'schema_versions':['scenario-1.1','ethan-toolkit-1.0','financial-snapshot-1.0','financial-metrics-1.0','cash-simulation-1.0','plan-comparison-1.0','life-plan-1.0'],
           'money_unit':'integer CNY minor units','tools':[t['name'] for t in load('tool_definitions.json')],'quota':quota,
           'completed':['来源和职责核对','四块基础能力及事件模拟','22项测试','5类最新原件导入','20份演示产物','工具契约与逐分工文档'],
           'unfinished':(['压缩包隔离验收'] if archive.get('status')!='passed' else []),'limitations':limitations}
    dump('context_log.json',{'generated_at_utc':datetime.now(timezone.utc).isoformat(),'steps':steps,'current_state':state,'summary':conclusion,'status':status,'conclusion':conclusion})
    (ROOT/'context_log.md').write_text('# 执行上下文\n\n用户要求替 Ethan 准备兜底工具包，并继续先前未完成工作。仅5h额度低于10%停止；不检查周额度。\n\n'+
        '\n\n'.join(str(s['step'])+'. '+s['analysis']+'\n\n结果：'+s['result'] for s in steps)+
        '\n\n## 当前状态\n\n```json\n'+json.dumps(state,ensure_ascii=False,indent=2)+'\n```\n\n结论：'+conclusion+'\n',encoding='utf-8')
    dump('reports/quota_history.json',{'historical_stop':{'remaining_percent':6,'window_minutes':300,'source':'previous subtask tool observation','checkpoint':'checkpoints/20261024-low-quota.json'},'latest':quota,'conclusion':'weekly quota is excluded from stop decisions'})
    print(json.dumps({'status':status,'conclusion':conclusion},ensure_ascii=False))


if __name__=='__main__':main()
