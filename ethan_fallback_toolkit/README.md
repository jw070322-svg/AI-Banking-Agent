# Ethan 兜底 Toolkit

项目分工要求环境生成、金融数据整理、确定性计算及生活场景计划；Ethan 最新 1022 交付主要覆盖 A–E 环境生成，缺少独立模块和完整验收。此包保留她的业务定义及导入兼容，补成独立、离线、可测试的工具包。

## 五分钟运行

只需 **Python 3.11+**，无需 pip、模型密钥、Node.js 或银行连接。

```powershell
cd F:\AI_Banking\ethan_fallback_toolkit
python verify_toolkit.py
python -m ethan_toolkit tools
python -m examples.main_agent_call
```

已有演示产物位于 [output/demo](output/demo)。重新生成到一个新目录：

```powershell
python -m ethan_toolkit demo --output-dir output/my-demo
python -m ethan_toolkit generate B --seed 42 --as-of 2026-10-24 --increase-minor 80000 --output output/shopping.json
python -m ethan_toolkit validate output/shopping.json
python -m ethan_toolkit call plan_life_event --input examples/life_request.json --output output/my-birthday.json
```

输出文件已存在会拒绝覆盖；明确希望替换时才加 `--force`。金额以**整数分**传入：80000 是 800 元。API 默认参考日固定为 2026-10-24，不暗中读取当天日期；CLI 生成须显式 `--as-of`。

## 能替 Ethan 兜底的部分

| 能力 | 已实现 | 直接查看 |
|---|---|---|
| 环境生成 | A 普通用户、B 购物增加、C 疑似重复、D 余额不足、E 周期订阅；固定 seed/date；金额和余额校验 | `output/demo/A.json` 至 `E.json` |
| 数据整理 | 保留原流水，核对账本；补“未分类/未知商户”标记；按期快照、来源哈希、疑似重复及订阅候选 | `output/demo/C_snapshot.json` |
| 金融计算 | 收入与冲回、消费与退款、转入转出、月度分类、现金结余率、债务偿付比、流动性月数 | `output/demo/A_metrics.json` |
| 事件模拟 | 按日期算期末/最低余额，比较预算、取消订阅、收入延迟；检查应急预留 | `output/demo/plan_comparison.json` |
| 生活场景 | 生日等事件预算、三段提醒日历、超预算阻止计划、ICS 导出 | `output/demo/birthday_plan.json`、`birthday_calendar.ics` |

生命周期计划只输出草稿，ICS 只是本地文本。没有自动预约、转账、锁钱或添加线上日历。不同生活事件可用 `label` 和日期指定；没有假装理解任意生活需求。

## 主 Agent 接入

```python
from ethan_toolkit.tools import call_tool

environment = call_tool("generate_environment", {
    "scenario_type": "A", "seed": 42, "as_of": "2026-10-24"
})
result = call_tool("calculate_financial_metrics", {
    "data": environment["data"]
})
```

[tool_definitions.json](tool_definitions.json) 提供 12 个工具的参数 schema。仅调用白名单函数，错误统一返回 rejected；详细契约见 [API-CONTRACT.md](API-CONTRACT.md)。验证函数发现不合格数据时也返回 rejected。

可将 `ethan_toolkit/` 整个包复制到主程序可导入的目录。它不依赖 F 盘路径。`to_agent_scenario` 能输出 SecondAsgent 的 scenario-1.0 展示结构；该简化结构省略商户/交易类型，**金融分析必须保留完整 scenario-1.1**。本次不自动替换 SecondAsgent 已运行服务，不修改其业务账本。

## 证据与协作

- [总版总结](summary.md) / [summary.json](summary.json)
- [Ethan 逐文件交接](handoff/Ethan.md) / [主 Agent 接入交接](handoff/integration.md)
- [测试报告](reports/verification.json) / [测试明细](reports/tests.txt)
- [原始 1022 样例导入验证](reports/ethan_import_verification.json)
- [来源清单](reports/source_manifest.json)；原件未覆盖，新代码的来源关系明确标注。
- [执行上下文](context_log.md) / [context_log.json](context_log.json)；只检查 5h 窗口，低于 10% 停止。

## 适用范围

这是规则与确定性工具层，未实现开放式 LLM、真实银行、随机未来收益模拟、Sharpe/VaR 或商户系统。固定种子生成的是测试环境，不代表概率预测。订阅候选、重复候选不等于事实确认。缺少来源明确的交易类型时拒绝分析；不会仅凭金额正负把转账算作工资或消费。信用卡还款须由上游明确标记为 transfer_out；不能自动解决任意原始银行账单的重复统计。

结论：本包能兜底 Ethan 当前分工中的确定性基础能力，可独立复跑并按统一工具接口接入主 Agent。
