# Module 6 · Tool Calling Layer 实现记录

> 整理时间：2026-10-29 00:20（Asia/Shanghai，UTC+8）  
> 项目目录：`/Users/eva-/ai-banking-agent`  
> 当前交付状态：Module 6 已实现、已测试；Risk Engine / Compliance Guard 适配器默认未接通；交易仅限模拟，默认失败关闭。

本文记录本次 Module 6 的工作思路、实现内容、修改记录和事件时间线，便于交接、复核和后续集成。

说明：

- 项目不是 Git 仓库，无法提供 commit 或 diff；修改记录依据本次会话操作、文件清单和文件 mtime 整理。
- 文件时间取自文件系统的最后修改时间，**不是首次创建时间**；会话中多次编辑会刷新 mtime。
- 非文件时间（如“检查现有代码”“运行基线测试”）为会话阶段时间，部分为约数，已用“约”标注。
- 本文记录的是可复核的设计依据与决策，不展开不可审计的内部推理过程。

---

## 1. 任务目标与边界

### 1.1 目标

为现有 AI Banking Agent 独立开发 **Module 6 — Tool Calling Layer**：

- 统一的 Tool Registry，可注册、发现、校验、调用和追踪工具；
- 初始 13 个工具，保持题目给定清单；
- 顺序与条件工具编排；
- 确定性金融计算；
- 证据收集、结构化结果聚合和 Markdown 报告；
- 单元测试与端到端测试；
- 为已完成的 Risk Engine / Compliance Guard 预留清晰集成接口。

### 1.2 必须遵守的边界

- **不重写、不替换、不修改**已完成模块：
  - `bank_agent/risk/`
  - 现有 `bank_agent/tools.py`
  - `bank_agent/orchestrator.py`
  - `bank_agent/stages/`
- 不复制其风险规则、合规规则或审批逻辑；
- 使用 mock 数据时明确标识；
- 敏感操作在安全检查未接通时必须失败关闭；
- 原型不得执行真实交易；
- 不声称已接入实际银行 API。

---

## 2. 初始调查与判断

### 2.1 现有系统结构

先阅读了：

- `README.md`、`docs/00`–`07`：了解既有架构、工具合同、风险边界；
- `bank_agent/tools.py`：旧流水线工具注册表和 MockBank 工具实现；
- `bank_agent/risk/`：Risk Engine、策略、预览、审批、Compliance Guard、Action Log；
- `bank_agent/orchestrator.py`、`stages/`：意图、规划、选择、执行、校验、回复；
- `bank_agent/data.py`：客户、账户、流水、贷款等确定性 mock 数据；
- `tests/test_pipeline.py`、`tests/test_risk_compliance.py`。

### 2.2 关键发现

1. 旧注册表 `bank_agent/tools.py` 与旧流水线深度耦合，工具名称、Plan 结构和执行业务逻辑都面向既有场景。
2. 已有 Risk & Compliance 模块使用“计划级”评估、预生成预览、用户确认、提交前重新校验和一次性审批，不是单次 `evaluate()` 能简单替代的。
3. 因此不能在旧注册表上直接叠加 13 个新工具，也不能为了让新工具工作而修改风险模块。
4. 最稳妥的做法是新增独立命名空间 `bank_agent.tool_calling`，复用确定性的 MockBank 数据，但不复用或改写 Risk/Compliance 的决策逻辑。

### 2.3 基线

修改前运行旧测试：

```text
Ran 42 tests ... OK
```

这成为后续回归基线。

---

## 3. 设计思路与关键决策

### 3.1 总体思路

```text
用户目标 / 外部规划器
        ↓
ToolPlan（声明式步骤、引用、条件、逐步确认）
        ↓
ToolOrchestrator（顺序、依赖、条件、聚合）
        ↓
ToolRegistry（注册、发现、验证、权限、幂等、安全门、执行）
        ↓
工具实现 / Mock 服务 / 安全适配器
        ↓
Evidence + Trace
        ↓
Markdown 报告
```

Registry 只负责工具本身；规划与编排在独立模块，避免工具层变成不可测试的“大总控”。

### 3.2 关键决策

| 决策 | 原因 | 代价 / 说明 |
|---|---|---|
| 新建 `bank_agent/tool_calling/`，不改造旧注册表 | 保护现有 42 个测试和已完成模块 | 两套注册表短期共存；文档明确二者用途 |
| 工具清单严格保持 13 个，无增删 | 遵循题目要求 | 旧流水线的 `query_transactions` 等名称保留，不迁移 |
| 使用标准库实现 JSON Schema 子集 | 仓库无依赖、离线可跑 | 只支持本模块需要的 Schema 子集 |
| 金额、利率、权重用 decimal 字符串 | 避免 float 精度问题；和金融输出保持可审计 | Schema 更严格，调用方需按字符串传值 |
| 所有成功结果返回统一 envelope | 错误、证据、安全状态和 trace 可被上层统一消费 | 各工具 data 仍保持领域字段 |
| 计算与数据服务分离 | 便于替换为真实 API 和单测 | 需要额外 service 注入层 |
| 风险/合规只做 adapter port | 不复制已完成业务逻辑，允许后续接通 | 默认不可用；不能宣称生产安全 |
| `execute_transaction` 默认失败关闭 | 安全优先 | 未接真实安全模块时不可执行；模拟路径也必须显式开启 |
| Mock 安全适配器必须显式开启 | 防止测试替身被误认为生产模块 | 需要 `allow_mock_safety=True` |
| 条件表达式只允许固定运算符 | 避免 eval、任意代码和注入 | 不支持复杂表达式；需要更复杂逻辑时扩展算子或编排层 |
| 使用确定性公式做金融测算 | 可复现、可测试 | 不是真实产品定价/投资建议 |
| `calculate_risk` 明确只做市场风险 VaR | 与已完成运营 Risk Engine 区分 | 不返回交易授权或运营风险结论 |
| 报告只基于工具输出和证据生成 | 防止 LLM/模板编造数字 | 报告可读性受结构化字段限制 |
| 交易仅接入显式 mock gateway | 原型不得动真实资金 | 非 simulated gateway 被 handler 拒绝 |
| 预算、提醒、幂等存储先做内存版 | 竞赛原型可快速运行 | 不持久；重启丢失；生产需数据库 |

### 3.3 为什么没有直接接现有 Risk Engine

现有 Risk Engine 的正确使用方式是“计划 → 评估/预览 → 确认 → 提交前重校验/授权”，而不是把一次工具调用压缩成一个布尔值。

本次没有实现它的桥接，原因：

- 任何桥接都必须保留计划、预览、确认、幂等消费和 step-up 的完整生命周期；
- 在没有完成该桥接和验收前，声称“风险检查已生效”是不诚实的；
- 题目也明确要求预留接口、说明未接通部分。

因此：

- 定义了类型化的 `RiskEngineAdapter`、`ComplianceGuardAdapter`；
- 默认注入 `Unconfigured*Adapter`，状态明确为 `not_connected`；
- 对 `execute_transaction`，要求两个端口均 ready，否则 `SAFETY_CHECKS_UNAVAILABLE`；
- mock 适配器只在测试中显式开启，并始终标记为 `evaluated_mock`。

---

## 4. 实现内容

### 4.1 统一 Tool Registry

位置：`bank_agent/tool_calling/registry.py`

实现能力：

- 工具注册、名称/版本/权限/数据源/风险等级校验；
- 严格禁止重复注册；
- 输入 Schema 默认值填充与校验；
- 输出 Schema 校验，失败不返回成功；
- 上下文权限检查；
- 确认要求检查；
- 幂等键检查、结果回放、冲突拒绝；
- 合规/风险适配器调用与 fail-closed；
- 工具执行、异常映射、trace、evidence；
- `discover()` / `list_tools()` / `describe()` / `execute()` / `call()` / `invoke()`。

### 4.2 13 个工具

| # | 工具 | 类型 | 风险等级 | 实现状态 |
|---|---|---|---|---|
| 1 | `get_account_balance` | 只读 | R1 | mocked |
| 2 | `get_transactions` | 只读 | R1 | mocked |
| 3 | `analyze_cashflow` | 只读 | R2 | mocked |
| 4 | `calculate_financial_health` | 只读 | R2 | mocked |
| 5 | `calculate_risk` | 只读 | R2 | mocked（固定市场假设） |
| 6 | `search_products` | 只读 | R2 | mocked |
| 7 | `compare_products` | 只读 | R2 | mocked |
| 8 | `retrieve_policy` | 只读 | R2 | mocked |
| 9 | `calculate_loan` | 只读 | R2 | implemented |
| 10 | `calculate_portfolio` | 只读 | R2 | mocked（固定市场假设） |
| 11 | `create_budget` | 状态变更 | R3 | mocked（内存存储） |
| 12 | `create_alert` | 状态变更 | R3 | mocked（内存存储、不发送通知） |
| 13 | `execute_transaction` | 状态变更 | R4 | awaiting_integration（仅模拟） |

工具列表未增删。旧流水线中的旧工具名保持不变。

### 4.3 编排

位置：`bank_agent/tool_calling/orchestration.py`

- 步骤顺序执行；
- `${step_id.path}` 引用前序工具结果，整体值替换、保留类型；
- 条件运算符白名单：`eq/ne/gt/gte/lt/lte/contains/in/exists/truthy`；
- 前置引用、未知工具、重复步骤、非法条件在**执行前**拒绝；
- 条件不满足记为 skipped；
- 可选步骤失败可继续；
- 必需步骤失败 fail-fast，后续 `not_run`；
- 必需步骤依赖失败/被跳过分支时记为 blocked，避免静默完成；
- 状态区分 `completed / partially_completed / failed / unknown`；
- 变更步骤按步骤 ID 生成稳定幂等键；
- 每个变更步骤需要独立的确认 ID，不能用一个确认覆盖多个变更。

### 4.4 安全接口

位置：

- `bank_agent/tool_calling/adapters.py`
- `bank_agent/tool_calling/mocks.py`
- `bank_agent/tool_calling/services.py`

实现：

- `RiskEvaluationRequest/Result`、`ComplianceEvaluationRequest/Result`；
- 生产适配器 readiness 契约：`adapter_kind="production"`, `is_connected=True`, `is_verified=True`；
- 默认占位适配器明确 `not_connected`；
- 合规检查在 handler 之前；风险检查在所有变更工具的 handler 之前；
- `execute_transaction` 强制要求两个适配器 ready；
- 适配器要求 step-up 时，缺少 `step_up_verified` 返回 `AUTH_INSUFFICIENT`；
- 安全适配器异常 fail closed；
- Mock 适配器需 `allow_mock_safety=True`，且结果标记为 `evaluated_mock`；
- 非 simulated 交易网关被 handler 拒绝。

### 4.5 金融计算

位置：`bank_agent/tool_calling/calculations.py`

- 现金流、月度/类别聚合、储蓄率、30 天月均值；
- 财务健康评分（应急金、储蓄能力、偿债压力、信用使用）；
- 贷款摊还（等额本息/等额本金，分位四舍五入，末期调整）；
- 组合确定性增长与压力情景；
- 市场风险 VaR、加权波动率、集中度 HHI。

全部使用 `Decimal`，无随机数和浮点金额计算。

### 4.6 证据、Trace、报告

- 每次成功调用生成 `EvidenceItem`：来源、采集时间、payload、SHA-256；
- 内存 trace 与可选 JSONL `JsonlTraceSink`；
- trace 只记录参数/结果哈希，不写原始参数或请求文本；
- `MarkdownReportGenerator` 只用结构化工具输出生成报告；
- 报告明确标注模拟数据、模拟交易、mock 安全适配器和未接通的生产检查；
- 幂等回放在报告中额外标注“返回原始结果，未重复执行副作用”。

### 4.7 数据边界

- 账户/流水/贷款：复用现有 `MockBank`（仅内存 demo 数据）；
- 产品目录、政策库：显式 mock；
- 预算、提醒：进程内 `PlanningStore`；
- 交易：仅 MockBank 模拟网关；真实网关不存在；
- 无真实银行、支付、短信/推送或 RAG 接入。

### 4.8 测试、文档、演示

- 4 个新测试文件，共 59 个测试；
- 架构文档：`docs/08-tool-calling-layer.md`；
- 演示：`scripts/demo_tool_calling.py`；
- README 增加 Module 6 说明、测试命令和演示入口。

---

## 5. 修改记录

### 5.1 新增文件

时间为最后修改时间（Asia/Shanghai）。

| 文件 | 最后修改 | 内容 |
|---|---|---|
| `bank_agent/tool_calling/tracing.py` | 2026-10-28 23:47:22 | trace sink / JSONL |
| `bank_agent/tool_calling/adapters.py` | 2026-10-28 23:47:32 | Risk/Compliance 适配器接口 |
| `bank_agent/tool_calling/tools/accounts.py` | 2026-10-28 23:49:04 | 余额、流水工具 |
| `bank_agent/tool_calling/tools/analysis.py` | 2026-10-28 23:49:30 | 现金流、财务健康、市场风险 |
| `bank_agent/tool_calling/tools/products.py` | 2026-10-28 23:49:51 | 产品检索、比较 |
| `bank_agent/tool_calling/tools/policies.py` | 2026-10-28 23:50:00 | 政策检索 |
| `bank_agent/tool_calling/tools/transactions.py` | 2026-10-28 23:50:51 | 敏感模拟交易 |
| `bank_agent/tool_calling/tools/__init__.py` | 2026-10-28 23:50:58 | 13 工具注册入口 |
| `bank_agent/tool_calling/mocks.py` | 2026-10-28 23:55:38 | TEST ONLY 安全替身 |
| `bank_agent/tool_calling/schema.py` | 2026-10-28 23:59:23 | JSON Schema 子集与校验 |
| `bank_agent/tool_calling/errors.py` | 2026-10-28 23:59:50 | 标准错误码 |
| `bank_agent/tool_calling/models.py` | 2026-10-28 23:59:51 | 数据上下文/定义/结果/证据 |
| `bank_agent/tool_calling/utils.py` | 2026-10-29 00:00:15 | Decimal/哈希/检索辅助 |
| `bank_agent/tool_calling/calculations.py` | 2026-10-29 00:00:27 | 确定性金融计算 |
| `bank_agent/tool_calling/services.py` | 2026-10-29 00:00:49 | Mock 数据/产品/政策/存储/网关 |
| `bank_agent/tool_calling/__init__.py` | 2026-10-29 00:01:48 | 公共导出 |
| `tests/test_tool_calling_registry.py` | 2026-10-29 00:02:10 | 18 个 Registry 测试 |
| `tests/test_tool_calling_tools.py` | 2026-10-29 00:02:33 | 14 个工具测试 |
| `tests/test_tool_calling_safety.py` | 2026-10-29 00:02:53 | 13 个安全测试 |
| `bank_agent/tool_calling/orchestration.py` | 2026-10-29 00:08:46 | 顺序/条件编排 |
| `tests/test_tool_calling_orchestration.py` | 2026-10-29 00:08:52 | 14 个编排/E2E 测试 |
| `scripts/demo_tool_calling.py` | 2026-10-29 00:08:18 | 可运行演示 |
| `docs/08-tool-calling-layer.md` | 2026-10-29 00:12:04 | Module 6 架构与工具合同 |
| `logs/2026-10-29-tool-calling-layer.md` | 2026-10-29 00:09:06 | 开发日志 |
| `logs/delivery-verification-20261029-001103.md` | 2026-10-29 00:11:03 | 既有交付验证脚本生成的最终日志 |
| `bank_agent/tool_calling/registry.py` | 2026-10-29 00:10:21 | 核心 Registry / dispatch / 安全门 |
| `bank_agent/tool_calling/reporting.py` | 2026-10-29 00:10:22 | 证据报告 |
| `bank_agent/tool_calling/tools/planning.py` | 2026-10-29 00:10:23 | 贷款、组合、预算、提醒 |
| `docs/09-module6-implementation-record.md` | 2026-10-29（本次整理） | 本实现记录 |

### 5.2 修改的既有文件

| 文件 | 修改时间 | 修改内容 |
|---|---|---|
| `README.md` | 2026-10-29 00:20:56 | 增加 Module 6 说明、文档链接、测试/演示入口、目录与测试数量更新；本次整理时增加本记录链接 |
| `.gitignore` | 2026-10-29 00:08:09 | 增加 `reports/`，避免提交演示生成物 |

本项目不是 Git 仓库，无法生成 diff；但已确认以下既有模块没有代码改动：

- `bank_agent/risk/`（全部文件）
- `bank_agent/tools.py`
- `bank_agent/orchestrator.py`
- `bank_agent/stages/`
- `bank_agent/data.py`
- 既有测试文件 `tests/test_pipeline.py`、`tests/test_risk_compliance.py`

### 5.3 实施过程中发生的关键修正

| 阶段 | 事件 | 处理结果 |
|---|---|---|
| 首次导入冒烟 | `object_schema` 不支持 nullable，导致 `create_alert` 注册失败 | 增加 `nullable` 支持；覆盖可空账户对象 |
| 中文检索验证 | 原按空格分词，`转账限额`、`稳健基金`、`提前还款` 召回不足 | 增加 CJK 二元组检索、最低匹配数和政策版本排序 |
| 安全检查冒烟 | fail-closed 错误 meta 只显示默认安全状态，未显示未接通细节 | 让 `_run_safety` 原地更新并保留未接通/拒绝状态 |
| 安全测试 | Risk 适配器要求 step-up 时注册表未强制 | 增加 `step_up_verified` 上下文和 `AUTH_INSUFFICIENT` 失败关闭 |
| 编排测试 | 必需步骤依赖被条件跳过的分支时可能静默跳过 | 改为 `blocked` + `DEPENDENCY_FAILED`，并补测试 |
| 输出契约 | 注册时只强制输入 Schema 严格，输出 Schema 未强制 `additionalProperties=false` | 注册时同样强制输出契约 |
| 报告幂等 | 回放结果没有在报告中标注为回放 | 报告增加“幂等重放，未重复副作用”提示 |
| 提醒语义 | 早期版本可能被误解为存在真实通知/监控 | 明确 `sent=false`、无后台触发引擎并写入 notes/文档 |
| 文档核对 | 测试数从 100 增至 101（新增依赖阻断用例） | README、docs/08、日志同步更新为 101 / 59 |

---

## 6. 事件时间线

> 说明：非文件事件使用会话阶段时间；文件事件使用 mtime。  
> 时区：2026-10-29 00:xx 为 Asia/Shanghai（UTC+8）。

| 时间 | 事件 | 结果 |
|---|---|---|
| 2026-10-28 23:40 左右 | 切换到 `ai-banking-agent`，检查项目结构 | 确认现有流水线、旧 Registry、Risk & Compliance 模块 |
| 23:40–23:47 约 | 阅读 README、工具层、风险模块、数据层、测试与文档；运行基线测试 | 基线 **42 passed** |
| 23:47–23:51 | 创建 Registry 基础接口、适配器/trace、账户/分析/产品/政策/交易工具 | Module 6 基本骨架落盘 |
| 23:55–00:00 | 完成 Mock 适配器、Schema 校验、错误模型、Mock 服务与确定性计算 | 13 工具具备可运行实现 |
| 2026-10-29 00:01–00:03 | 创建包导出、Registry/工具/安全测试 | 首轮测试通过 |
| 00:03–00:08 约 | 冒烟测试、修正 nullable、改进中文检索、补编排/端到端测试、添加演示脚本 | 顺序/条件编排与报告路径可用 |
| 00:08–00:10 | 修正依赖阻断语义、安全 fail-closed meta、step-up 门、输出 Schema、报告幂等标注 | 安全与契约行为收紧 |
| 00:11:03 | 运行既有 `scripts/verify_delivery.py` | **101 tests passed**；原旧转账 Demo 仍生成 3 条日志 |
| 00:12 左右 | 更新 `docs/08`、README、最终测试和两种演示模式 | 默认演示 9/9 步；mock 交易演示 10/10 步 |
| 00:13–00:18 约 | 删除生成报告、复核文件结构与统计 | 仅保留源码、测试、文档、日志；演示报告可重新生成 |
| 00:19–00:20 | 整理本实现记录 | 本文档生成 |

---

## 7. 验证记录

### 7.1 全量测试

```bash
cd /Users/eva-/ai-banking-agent
python3 -m unittest discover -s tests -v
```

结果：

```text
Ran 101 tests in 0.210s
OK
```

构成：

- 既有 42 个测试：10 个流水线 + 32 个 Risk & Compliance；
- Module 6 新增 59 个：
  - Registry 18
  - Tools 14
  - Safety 13
  - Orchestration / E2E 14

### 7.2 既有交付验证

```bash
python3 scripts/verify_delivery.py
```

结果：

```text
status: passed
tests: 101 tests
demo: completed · 3 logs
manifest files: 31
```

说明：该脚本仍按既有 Risk & Compliance 交付清单校验；Module 6 测试通过同一测试发现命令被一并执行。

### 7.3 Module 6 演示

只读演示：

```bash
python3 scripts/demo_tool_calling.py
```

结果：

```text
Plan status: completed
9 steps succeeded
9 evidence items
```

模拟交易演示：

```bash
python3 scripts/demo_tool_calling.py --mock-transaction
```

结果：

```text
Plan status: completed
10 steps succeeded
10 evidence items
NOTE: the transfer receipt is simulated; no real funds moved.
```

演示生成的报告写入被 `.gitignore` 排除的 `reports/`，可删除后重新生成。

### 7.4 已覆盖的关键断言

- 未连接安全适配器时 `execute_transaction` 不改变余额；
- 注入 mock 安全适配器但未显式开启 `allow_mock_safety` 时仍失败关闭；
- Compliance/Risk 拒绝时无交易副作用；
- step-up 未验证时拒绝；
- 非 simulated 网关被拒绝；
- 只有只读工具可对显式标记的 transient error 重试；
- 变更工具不自动重试；
- 未知变更结果不报告为成功；
- 幂等重复不重复扣款；同键不同参数返回冲突；
- 参数/结果中的 PII 不以明文进入 trace；
- 其他客户账户不可查询；
- 报告不声称生产风险/合规检查已运行。

---

## 8. 当前安全与集成状态

| 能力 | 状态 | 说明 |
|---|---|---|
| Risk Engine | **未接通** | 只有 adapter port 和默认占位实现；未修改既有模块 |
| Compliance Guard | **未接通** | 只有 adapter port 和默认占位实现；未修改既有模块 |
| `execute_transaction` | **默认 fail closed** | 缺任一必需适配器即拒绝，不触达 handler |
| 模拟安全适配器 | 仅测试/演示 | `allow_mock_safety=True` 才启用；报告标 `evaluated_mock` |
| 真实交易网关 | **不存在** | 只允许 `simulated=True` 的网关；非模拟网关被拒绝 |
| 真实银行 API | 未接入 | MockBank |
| 产品/政策数据 | Mock | 目录与政策库显式标注模拟 |
| 预算/提醒 | 内存 | 重启丢失；不触发真实通知或扣款 |
| 幂等存储 | 进程内 | 非分布式；并发边界未达到生产要求 |
| Action Log | 未接 | Module 6 使用自己的 trace/evidence，不写既有 8 字段 Action Log |

---

## 9. 已知限制与后续工作

1. **Risk/Compliance 桥接未完成**：后续 adapter 必须保留既有预览、确认、提交前重校验、step-up 和一次性消费语义，不能把 R4 降级为一个布尔值。
2. **生产幂等**：把进程内字典替换为数据库唯一约束/事务。
3. **超时、熔断、限流**：当前只有 `max_attempts` 的只读重试；没有强制超时。
4. **真实数据服务**：接入真实账户、产品、政策/知识 RAG 服务。
5. **认证与审批**：当前的确认 ID 和 step-up 标志是受信任编排上下文，不是生产级用户证明；应接入既有审批/OTP/生物识别。
6. **PII 与提示注入防护默认未运行**：未接 Compliance Guard；政策文本已标记为不可信参考，报告目标文本的脱敏仍需接入。
7. **输出侧合规扫描**：未实现；生产应在工具输出进入回复/报告前接入 guard。
8. **多版本工具**：当前一个工具名只注册一个版本；版本号在结果中返回，但尚无并存/灰度机制。
9. **并发幂等竞争**：registry 有进程内锁，但两个并发同键请求仍可能都到达 handler；下游必须提供最终唯一性。
10. **报告文本**：报告为确定性 Markdown，不替代人类业务复核，不构成投资、信贷或交易建议。

---

## 10. 复现与相关入口

```bash
# 全部测试
python3 -m unittest discover -s tests -v

# 仅 Module 6
python3 -m unittest discover -s tests -p 'test_tool_calling_*.py' -v

# 只读演示
python3 scripts/demo_tool_calling.py

# 模拟交易演示（不是真实资金）
python3 scripts/demo_tool_calling.py --mock-transaction

# 既有交付验证
python3 scripts/verify_delivery.py
```

相关文件：

- 架构与 13 工具合同：[docs/08-tool-calling-layer.md](08-tool-calling-layer.md)
- 开发日志：[logs/2026-10-29-tool-calling-layer.md](../logs/2026-10-29-tool-calling-layer.md)
- Registry：[bank_agent/tool_calling/registry.py](../bank_agent/tool_calling/registry.py)
- 编排：[bank_agent/tool_calling/orchestration.py](../bank_agent/tool_calling/orchestration.py)
- 安全适配器：[bank_agent/tool_calling/adapters.py](../bank_agent/tool_calling/adapters.py)
- 报告生成：[bank_agent/tool_calling/reporting.py](../bank_agent/tool_calling/reporting.py)
- 演示脚本：[scripts/demo_tool_calling.py](../scripts/demo_tool_calling.py)
