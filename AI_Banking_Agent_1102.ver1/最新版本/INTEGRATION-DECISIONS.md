# 跨板块整合决议

## 运行基线

SecondAsgent 为完整执行基线，新增代码只落在 Third_Agent。Ethan 的 FirstAgent 参考是接入材料，不能覆盖新版卡管理。

## 推荐金额

读取 organizer 的 recommendation 视图；最终金额再取 min(视图预算, 原引擎 capacity, 当前配置)。分析上限为零沿用配置/引擎约束，并保留应急金提示；缺 read 或模块不可用时回退旧规则。

## 卡管理

复用原卡预览/验证/确认/审核/回执。analysis_bridge 投影当前卡状态、限额、当日已用；不把信用卡额度当成存款，不伪造信用卡账单。

## 界面数据

实时资金、授权、操作状态继续使用 /api/snapshot；display 只供只读分析，不覆盖 UI 账本。Agent 面板增加分析和整理按钮，生成按钮显式用 contract 格式。

## 整理入口

新增 data.organize，纳入 /api/analysis 会话工具白名单；仅服务端派生上下文、只读、有 read 授权。CLI/纯函数继续可用。

## 生成契约

新 A–G 生成走 Ethan 唯一 scenario_adapter；prompt 或 format=contract 返回新契约。requirement 无 format 保留旧 scenario-1.0 投影，签名金额不同，不能互相猜测。

## 接入路径

first_agent/analysis_bridge.py 在新交付包中为共享接入基线；模块位于 modules/，默认不再依赖队友 Desktop 路径。环境变量 AI_BANKING_ANALYSIS_DIR 仍支持成对模块的替换。

## 知识模块

客户账本和整理视图不进入 RAG；沿用八篇知识原文、BM25 与证据引用。

## 待真实数据

没有用户提供的脱敏数据，不能宣称校准完成；保留为明确外部依赖，不用合成数据冒充真实数据。

以上为本轮集成实现选择，不冒称队友已逐人确认。未向队友或外部服务发消息。

整合测试 59/59；JS 规则 35/35；分析 115 项；环境生成 73 项。
