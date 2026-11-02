# AI Banking｜环境生成 Agent 逻辑链与交接说明

> 更新时间：2026-10-24。用途：由环境生成 Agent 模块交接给主任务「金融分析与量化」，
> 说明两模块如何通过契约协调，以及当前进度、边界和下一步。

## 1. 三个模块的位置与职责

| 模块 | 路径 | 职责 | 状态 |
|---|---|---|---|
| 环境生成 Agent | `AI_Banking\环境生成agent` | 按需求生成虚构场景数据，校验后产出契约 JSON | 已收尾（73 项测试） |
| 主任务（分析与量化） | `AI_Banking\主任务_金融分析与量化` | 账单报告、异常识别、订阅负担、现金流、流动性、预算建议 | 第一版完成（115 项测试） |
| FirstAgent（集成主服务） | `Desktop\FirstAgent` | 统一账本、HTTP 接口、接入上述两模块 | 已接入（34 项测试） |

三者不在同一仓库，靠**路径引用 + 契约格式**协作，不复制代码。

## 2. 完整逻辑链

```text
┌─────────────────────────────────────────────────────────────────┐
│ 1. 环境生成 Agent（AI_Banking\环境生成agent）                      │
│    自然语言需求 → parse → generate(A~G) → 双层校验 → 契约适配       │
│    输出：契约场景 JSON（整数分、booked、ledger_modified=false）     │
└───────────────────────────────┬─────────────────────────────────┘
                                │ 契约场景 JSON（统一边界）
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. 主任务（AI_Banking\主任务_金融分析与量化）                       │
│    bridge.py 调用环境生成   pipeline.py 端到端分析                 │
│    analysis/ 账单报告、异常、订阅负担、现金流、流动性               │
│    tools.py 暴露 9 个只读工具                                     │
└───────────────────────────────┬─────────────────────────────────┘
                                │ call_tool() / 契约 JSON
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. FirstAgent（Desktop\FirstAgent）                              │
│    analysis_bridge.py：会话账本 → 契约场景 → 分析工具              │
│    /api/analysis、/api/scenarios/generate、/api/analysis/status  │
│    账本、幂等、审计在 SQLite 同一事务；分析只读不改账本            │
└─────────────────────────────────────────────────────────────────┘
```

**关键原则：三个模块只通过「契约场景 JSON」通信**。契约格式是唯一边界，
任何一侧改了内部结构，只要契约不变，另一侧无需改动。

## 3. 环境生成 Agent 现状

### 支持场景（A~G）

| 类型 | 名称 | 专项校验要点 |
|---|---|---|
| A | 普通银行用户 | 同时有收入与支出 |
| B | 购物支出增加 | 两个月购物差额按真实流水重算 |
| C | 疑似重复扣款 | duplicate_group_id 归组、related_transaction_id 双向关联、保留正常交易 |
| D | 余额不足 | 被拒 transfer_out 超余额、无负余额 |
| E | 周期性订阅 | 固定金额/商户/连续月份/每月同日 + subscriptions 区块 |
| F | 家庭生日跨场景联动 | 配偶生日在锁定月、生日前 2 天鲜花蛋糕、日历不超预算 |
| G | 信用卡与卡片管理 | 借记卡+信用卡、账单、提额/限额/冻结解冻/挂失补卡 |

### 所有场景共享区块

`cards`、`credit_card_bill`、`family`、`calendar_events`、`expected_insights`；
E 额外 `subscriptions`，G 额外 `card_events`，F 额外 `budget` / `activity_calendar`。

### 关键文件

| 文件 | 作用 |
|---|---|
| `main.py` | 入口、解析、A~G 生成、双层校验、保存、seed/日期可复现 |
| `banking_domain.py` | 卡片、账单周期、家庭、节日、日历提醒 |
| `validator.py` | 结构 + 对账 + A~G 专项 + 卡片/账单/日历/洞察校验 |
| `scenario_adapter.py` | 契约适配：整数分、booked、去 PII、幂等、响应外壳 |
| `scenario_server.py` | 标准库 HTTP 入口（独立调试用） |

### 可复现

`set_seed(seed)` + `set_reference_date("YYYY-MM-DD")`，同一 seed+日期生成完全相同数据。
命令行：`python main.py --all --seed 42 --reference-date 2026-10-23`。

## 4. 主任务分析模块现状

### 9 个只读工具（tools.py）

`scenario.generate`、`bills.summary`、`bills.categories`、`anomalies.detect`、
`subscriptions.burden`、`cashflow.project`、`liquidity.available`、
`budget.advice`、`analysis.pipeline`。

### 识别与模型能力

- 账单分类 / 月度 / 年度报告（整数分）；
- 9 类异常与提醒：重复扣款、失败转账、还款、订阅续费、订阅调价、生日、预算锁定、工资、异常大额消费；
- 订阅负担率（月均、占工资比、分级）；
- 现金流投影（30/90 天、最低余额、缺口日）；
- 跨场景流动性（锁定预算后可用金额、挤占预警）；
- 预算建议（每月可安全储蓄/投资额、结余/流动性约束、建议动作）；
- 预算建议参数化回测（A~G × 6 种压力 × 2 个周期 × 13 种缓冲策略）；
- 数据整理 Agent（契约场景 → analysis / recommendation / cards / display 视图 + 质量清单）；
- 26 个扰动/对抗样例，防止误报回归。

### 评测

用环境生成的 `expected_insights` 当标准答案，A~G 样例 P/R/F1 = 1.0；
扰动样例 26/26 通过，FP 0 / FN 0。**注意：这是同源规则下的结果，不等于真实数据准确率。**

## 5. FirstAgent 接入现状

`first_agent/analysis_bridge.py` 把持久化会话账本转成契约场景再调分析工具。

- `POST/GET /api/analysis`：8 个只读分析工具（含 `budget.advice`；会话内不可调用 `scenario.generate`）；
- `POST /api/scenarios/generate`：通过主任务 bridge.py 调用环境生成 Agent；
- `recommend`：已授权 `read` 时用 `budget.advice.investment.headroom_minor` 收紧推荐金额；
  建议为 0 时保留原配置并提示先补应急金，分析不可用自动回退；响应 `budget_basis` 标注来源；
- `GET /api/analysis/status`：分析模块自检；
- `/api/health` 返回 `analysis.available`；
- 分析前后账本余额与版本不变，响应恒为 `simulated=true`、`ledger_modified=false`；
- 权限仍由 `consent.read` 控制。

## 6. 数据契约（关键转换规则）

| 字段 | 环境生成内部 | 契约格式（对外） |
|---|---|---|
| 金额 | 人民币元（float） | 整数分 `*_minor`；账单支出为负、收入为正 |
| 交易状态 | `completed` | `booked` |
| 交易方向 | `transaction_type` | 加 `direction`(credit/debit) |
| 用户信息 | 含身份证/手机/邮箱/住址 | 去除，只保留去标识化 profile |
| 卡号 | 完整 | 脱敏 `6222 **** **** 1234` |
| 账本 | 可写 | `ledger_modified=false`，只生成/只读 |

类别映射：环境生成用中文类别（购物/餐饮/订阅/工资…），FirstAgent 会话账本用英文
code（shopping/dining/subscription/income…），由 `analysis_bridge.CATEGORY_MAP` 统一成中文。

## 7. 已知边界与协调注意（重要）

1. **会话账本交易是月度汇总样本**（如"餐饮汇总样本"），不是逐笔流水，因此重复扣款
   识别在会话账本上不会触发；逐笔重复扣款只在环境生成的 C 场景里可用。
2. **会话账本没有信用卡账单、家庭成员生日、活动日历**，所以还款提醒、生日联动、
   锁定流动性在会话下为空；这些能力在 A~G 场景里完整可用。
3. ~~`scenario_adapter.py` 与 `first_agent/scenarios.py` 职责重叠~~——已核实为过期信息：
   FirstAgent 中没有 `scenarios.py`，契约适配只有 `scenario_adapter.py` 一套实现，无需合并。
4. **农历节日只覆盖 2026–2027**，是演示对照表，不是专业历法库；其他年份自动跳过。
5. **`expected_insights` 是评测用标准答案**，绝不能进对客回答；`scenario.generate`
   和 `analysis.pipeline` 都默认不返回，只有显式 `include_evaluation=true` 才保留。
6. **幂等结果已持久化到 SQLite**（环境生成侧，2026-10-24）：默认
   `runtime/idempotency.sqlite3`，可用 `ENV_AGENT_IDEMPOTENCY_DB` 覆盖；
   重启后可重放；只保证单机，不覆盖多实例/分布式。
7. **分析模块路径依赖**：FirstAgent 默认从 `../AI_Banking/主任务_金融分析与量化` 导入，
   可用环境变量 `AI_BANKING_ANALYSIS_DIR` 覆盖；缺失时返回 `ANALYSIS_UNAVAILABLE`，不影响账本。
8. **`expected_insights` 对客泄漏已堵住**（2026-10-24）：
   `tools.call_tool("scenario.generate")` 默认剥离 `expected_insights` 与
   `evaluation_only_fields`，只有显式 `include_evaluation=true` 才返回；
   FirstAgent 的 `POST /api/scenarios/generate` 复用该工具，因此自动生效。
   `analysis.pipeline` 保持原有 `include_evaluation` 开关。

## 8. 下一步（供主任务继续）

1. ✅ **比赛演示脚本**（2026-10-24 完成）：`AI_Banking/demo_full_chain.py`，
   一条命令跑通 转账 → 账单分析 → 订阅续费 → 生日锁定 → 流动性；
   两条验证：分析前后账本逐字段不变、删除 `expected_insights` 后结果不变。
2. ✅ **预算建议**（2026-10-24 完成）：`budget.advice` 输出每月可安全储蓄
   （保留 1 个月支出）与可安全投资（保留 3 个月支出）金额，并标明约束来源。
3. ✅ **理财推荐接入预算建议**（2026-10-24 完成）：`recommend` 用分析得出的
   `investment.headroom_minor` 收紧可投金额；为 0 时保留配置并提示先补应急金；
   响应新增 `budget_basis`，可追溯金额来源。
4. ✅ **合成场景参数化回测**（2026-10-24 完成）：`backtest_budget.py`，
   1092 次策略组合全部通过；发现并修正跨月工资取数问题，报告见
   `主任务_金融分析与量化/reports/budget_backtest.md`。
5. ✅ **数据整理 Agent**（2026-10-24 完成）：`organizer.py` 把契约场景投影为
   analysis / recommendation / cards / display 四视图 + 质量清单；20 项测试通过。
6. **真实脱敏数据回测**：校准类别阈值、订阅负担分级、锁定比例，
   以及 1/3 个月缓冲策略。
7. ✅ **堵住 `expected_insights` 泄漏**（2026-10-24 完成）：`scenario.generate`
   默认剥离，`include_evaluation=true` 才返回；FirstAgent 自动继承该行为。
8. **拆分 scenario_generator.py**：环境生成侧 main.py 只保留解析/校验/保存。
9. ✅ **幂等存储改 SQLite**（2026-10-24 完成）：`scenario_adapter.py` 使用单机
   SQLite 持久化，新增 3 项重启/持久化测试；跨进程重启验证同 key 返回相同场景。

## 9. 验证状态

```text
环境生成 agent：73 项测试通过
主任务分析模块：115 项测试通过（含 bridge 3 + pipeline 7 + tools 16 + budget 10 + backtest 7 + organizer 22）
FirstAgent：34 项集成测试通过（20 原有 + 14 分析），verify_delivery 结论 passed
环境生成 A~G 样例：P/R/F1 = 1.0；扰动样例 26/26 通过
全链路演示：demo_full_chain.py 退出码 0（普通档 ¥800 + 红档 ¥1200 各跑一次）
对客泄漏检查：FirstAgent /api/scenarios/generate 返回不含 expected_insights
预算回测：1092 次策略组合全部通过
规则稳定性：reports/budget_backtest_rule_stability.md
数据边界：reports/budget_backtest_data_boundaries.md
幂等持久化：同 key 跨进程重启返回相同 scenario_id，SQLite 保留 1 条记录
数据整理 Agent：20 项测试通过；F 推荐视图 budget_cny=10835.68，G cards 视图可用
```

运行命令：

```powershell
# 环境生成
cd "C:\Users\111\Desktop\AI_Banking\环境生成agent"
& "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe" -m unittest discover -s . -p "test_*.py"

# 主任务
cd "C:\Users\111\Desktop\AI_Banking\主任务_金融分析与量化"
& "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe" -m unittest discover -s . -p "test_*.py"
& "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe" cli.py pipeline --prompt "配偶生日，锁定 1000 元预算" --scenario-type F --seed 42 --reference-date 2026-10-23
& "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe" backtest_budget.py

# FirstAgent
cd "C:\Users\111\Desktop\FirstAgent"
& "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe" verify_delivery.py

# 全链路演示（比赛现场一条命令）
cd "C:\Users\111\Desktop\AI_Banking"
& "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe" demo_full_chain.py
```
