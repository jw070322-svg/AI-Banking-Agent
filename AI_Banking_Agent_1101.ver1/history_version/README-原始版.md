# AI Banking · Third_Agent

以 SecondAsgent 的执行链整合 Ethan 2026-10-24 ver.1 的环境生成、金融分析和数据整理。原目录保留；全部金融行为为本地模拟。

## 启动

需要 Python 3.11+、Node.js 18+；仅标准库，无需安装新依赖。

```powershell
cd F:\AI_Banking\Third_Agent
python -m first_agent.server --port 8768
# 或 .\run_agent.ps1
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

本轮证据：整合测试 59/59；JS 规则 35/35；分析 115 项；环境生成 73 项。最终状态：passed。详细日志在 reports/。

## 文件入口

- `first_agent/`：单一会话账本、执行控制和只读分析桥；Python 包名保留 first_agent。
- `modules/主任务_金融分析与量化/`：Ethan 分析、organizer 和回测源码；算法原样复用。
- `modules/环境生成agent/`：Ethan A–G 生成、双层校验、唯一契约适配与 SQLite 幂等。
- `web/`：原页面及新增分析、整理、A–G 生成入口。
- [统一接口](API-CONTRACT.md)、[整合决议](INTEGRATION-DECISIONS.md)、[总版总结](summary.md)、[上下文](context_log.md)。
- `reports/branches/`：Ethan、eva、vv、YUKI 与集成分工交接；`reports/history/` 保留历史。
- `sources/`：参考快照；不是运行入口。

## 边界

- 规则驱动、本地模拟；没有接入开放式大模型或真实 MFA。真实银行由组委会本地部署接入，沿用已确认交付边界。
- 真实脱敏流水未提供，未做真实数据校准；同源评测不是现实准确率。
- 会话仍是月度汇总样本，无逐笔重复扣款依据、信用卡明细、家庭生日及活动日历。会话卡片直接投影当前持久化状态，缺失账单不编造。
- 生成的 A–G 与会话账本独立；F 的生日锁定仅为合成场景预测，不改变会话资金。
- 推荐是偏好排序；分析上限为零保留配置并警告，不能解释为可投资建议；执行仍独立走原审批链。
- SQLite 幂等和审计限单机；不声称分布式事务、生产防篡改或生产认证。
- 同步 XHR、原有两套虚构联系人名册继续保留；未进行全尺寸与无障碍全面验收。
- 农历节日仅 2026–2027 演示对照表；未拆分上游 scenario_generator.py，保持已验证算法源码。
- 兜底 ethan_fallback_toolkit 保持独立；它的 scenario-1.1 不与 Ethan 的 1.0.0 混用，不接入第二套现金流算法。
- 原 eva 完整依赖与 YUKI 全量 50 题评测仍按历史边界处理，本轮未宣称补齐。

<!-- macro-quant-research:start -->
## 宏观量化研究增量（2026-10-24）

新增独立离线模块 [建模说明](research/macro_quant/项目目标与思路.md)、[参数与字段](research/macro_quant/params.json)、[核心代码](research/macro_quant/quant_recommender.py)。采用共同期限情景、宏观条件概率和均值/CVaR评分；原偏好推荐、预算回退、业务账本及审批规则保持不变。

接口新增的是 [离线契约](research/macro_quant/INTERFACE.md)，没有新增HTTP路由。真实数据尚未接入，合成验证不代表市场有效性。本增量状态与证据分别见 [接续记录](research/macro_quant/context.json) 和 [验证报告](research/macro_quant/verification.json)；不并入此前整合测试计数。
<!-- macro-quant-research:end -->
