# Third_Agent 执行上下文与接续记录

更新：2026-10-24T13:00:41+08:00。当前验证状态：passed。

## 开发路径核对

1. 通读历史上下文、当前交接及实际代码，识别 FirstAgent 与 SecondAsgent 版本差异。
2. 复制完整执行基线并保存来源哈希；排除原运行数据库，保留原交付目录。
3. 复跑未改动的分析 115、环境 73、核心执行 20 项基线；受限临时目录失败后经授权复跑通过。
4. 适配会话、分析/整理路由、推荐消费、场景兼容及页面按钮；所有算法模块 Python 保持来源字节一致。
5. 初次回归发现旧聊天多工具数量从 2 变 3；将分析结果替代旧账单查询，保持旧测试原断言不变。
6. 执行完整回归、预算回测和 800/1200 元演示；生成接口、总版、分工、差异与上下文。

## 上下文优先级

源记录完整保留。FirstAgent “卡操作未实现”是旧版本事实；SecondAsgent 已验证的卡操作优先。Ethan “不存在 scenarios.py”仅适用于其接入仓库，本地 SecondAsgent 确有该旧文件。Third_Agent 公共生成已改用最新 adapter，旧文件只供历史兼容测试。历史额度和中止记录不作为本次测试证据。

## 本轮决策

### 运行基线

SecondAsgent 为完整执行基线，新增代码只落在 Third_Agent。Ethan 的 FirstAgent 参考是接入材料，不能覆盖新版卡管理。

### 推荐金额

读取 organizer 的 recommendation 视图；最终金额再取 min(视图预算, 原引擎 capacity, 当前配置)。分析上限为零沿用配置/引擎约束，并保留应急金提示；缺 read 或模块不可用时回退旧规则。

### 卡管理

复用原卡预览/验证/确认/审核/回执。analysis_bridge 投影当前卡状态、限额、当日已用；不把信用卡额度当成存款，不伪造信用卡账单。

### 界面数据

实时资金、授权、操作状态继续使用 /api/snapshot；display 只供只读分析，不覆盖 UI 账本。Agent 面板增加分析和整理按钮，生成按钮显式用 contract 格式。

### 整理入口

新增 data.organize，纳入 /api/analysis 会话工具白名单；仅服务端派生上下文、只读、有 read 授权。CLI/纯函数继续可用。

### 生成契约

新 A–G 生成走 Ethan 唯一 scenario_adapter；prompt 或 format=contract 返回新契约。requirement 无 format 保留旧 scenario-1.0 投影，签名金额不同，不能互相猜测。

### 接入路径

first_agent/analysis_bridge.py 在新交付包中为共享接入基线；模块位于 modules/，默认不再依赖队友 Desktop 路径。环境变量 AI_BANKING_ANALYSIS_DIR 仍支持成对模块的替换。

### 知识模块

客户账本和整理视图不进入 RAG；沿用八篇知识原文、BM25 与证据引用。

### 待真实数据

没有用户提供的脱敏数据，不能宣称校准完成；保留为明确外部依赖，不用合成数据冒充真实数据。

## 已读上下文

- `../AI_Banking_赛题对照与方向校准_2026-10-19.md`
- `../FirstAgent/context_log.md`
- `../SecondAsgent/context_log.md`
- `../SecondAsgent/reports/branches/Ethan.md`
- `../ethan_fallback_toolkit/context_log.md`
- `../ethan_fallback_toolkit/handoff/integration.md`
- `sources/Ethan_1024/主任务_任务进度与数据_2026-10-24.md`
- `sources/Ethan_1024/主任务_任务进度与数据_2026-10-24.json`
- `sources/Ethan_1024/AI_Banking_环境生成_逻辑链与交接.md`
- `sources/Ethan_1024/数据整理Agent_逻辑链与接口.md`
- `modules/环境生成agent/AI_Banking_项目进度.md`
- `modules/环境生成agent/AI_Banking_上下文与进度.json`

## 当前证据与限制

整合测试 59/59；JS 规则 35/35；分析 115 项；环境生成 73 项。完整证据见 reports/verification.json。

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
