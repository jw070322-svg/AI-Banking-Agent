# AI Banking｜环境生成 Agent 项目进度记录

> 最近更新：2026-10-23（第二轮：卡片、生日/节日、日历提醒、智能检测）。
> 下次继续时可将本文件提供给助手，快速接续项目。

## 项目目标

开发一个独立的银行场景环境生成 Agent，按自然语言需求生成虚构的用户、账户、卡片、交易和生活事件数据，程序化校验后保存为 JSON，并可通过统一 API 契约提供给 AI Banking 主 Agent 使用。该 Agent 不连接真实银行、不执行资金操作，也不负责回答银行客户问题。

## 项目目录与文件

项目目录：`C:\Users\111\Desktop\AI_Banking\环境生成agent`

```text
环境生成agent/
├── main.py                 # 入口、需求解析、A~G 生成、双层校验、保存、命令行批量模式
├── main_backup.py          # 旧版 main.py 备份（未同步后续修改）
├── banking_domain.py       # 卡片、家庭、节日、日历提醒等"生活层"数据
├── validator.py            # 结构 + 对账 + A~G 专项 + 卡片/日历/洞察通用校验
├── scenario_adapter.py     # 统一接口 1.0.0 适配层（整数分、booked、去 PII、幂等）
├── scenario_server.py      # 本地 HTTP 入口（仅标准库）
├── test_validator.py       # validator 单元测试（39 项）
├── test_main.py            # 生成 + 双层校验集成测试（11 项）
├── test_adapter.py         # 契约适配测试（20 项）
├── AI_Banking_项目进度.md   # 本进度文件
├── output/                 # 生成的场景 JSON（内部格式，人民币元）
└── project/                # 当前为空
```

`scenario_generator.py` 和 `models.py` 仍未拆分；生成逻辑在 `main.py`，生活层在 `banking_domain.py`，数据仍用 dict。

## 用户视角：一个银行 App 用户会遇到什么

这一轮先按"用户会用到什么"列场景，再倒推生成什么数据：

| 用户会遇到的场景 | 生成的数据 | 对应比赛场景 |
|---|---|---|
| 借记卡日常消费、查余额 | `accounts` + `transactions` + `cards`(debit) | 账单分析 |
| 信用卡消费、账单日、还款日、最低还款 | `cards`(credit) + `credit_card_bill` + 还款提醒 | 账单分析 / 卡片管理 |
| 卡片挂失、冻结/解冻、提额、交易限额、补卡 | `card_events`（含 before/after 快照） | 卡片管理 |
| 工资到账、发薪日固定 | `salary_detected` 洞察 + 工资日提醒 | 账单分析 |
| 家人生日（配偶/父母/子女/兄弟姐妹） | `family` + 生日事件 + 生日洞察 | 跨场景联动 |
| 母亲节、父亲节、中秋、春节等节日 | `calendar_events`(festival) | 提醒 / 跨场景联动 |
| 生日当月锁定活动预算、订鲜花蛋糕 | `budget` + `activity_calendar` | 跨场景联动 |
| 订阅自动续费、想取消 | `subscriptions` + 续费提醒 | 订阅/代扣管理 |
| 备忘（体检、车险、公积金） | `calendar_events`(custom) | 日历/提醒 |
| 疑似重复扣款、异常大额消费 | `expected_insights`（带证据交易 ID） | 账单分析 / 异常识别 |

## 当前支持的场景（A~G）

- **A 普通银行用户**：工资 + 日常消费 + 卡片 + 日历 + 洞察。
- **B 购物支出增加**：两个月购物差额（按真实流水校验）。
- **C 疑似重复扣款**：重复组 + 双向关联 + 重复扣款洞察。
- **D 余额不足**：被拒转账，不计入余额。
- **E 周期性订阅**：多期扣款 + `subscriptions`（下次扣费日/状态）+ 续费提醒。
- **F 家庭生日跨场景联动**：配偶生日、锁定预算、生日前 2 天鲜花/蛋糕日历。
- **G 信用卡与卡片管理**：借记卡+信用卡、本期账单、卡片事件（提额/限额/冻结解冻/挂失补卡）、还款提醒。

## 本轮关键修改（2026-10-23 第二轮）

### 1. 新增 `banking_domain.py`：把"生活层"独立出来

- 卡片：`make_cards()` 生成借记卡和信用卡，额度关系 `可用 = 额度 - 已用`；卡号脱敏为 `6222 **** **** 1234`。
- 信用卡账单：`statement_period()` 计算账单周期，`make_credit_card_bill()` 计算本期消费、最低还款、已还、未还，并回写卡片已用额度。
- 家庭：`make_family()` 生成 1~3 位家庭成员，生日是"下一次生日"，带 `birth_year`、`age_turning`。
- 节日：公历节日 + 母亲节/父亲节/感恩节（按星期规则）+ 2026–2027 农历节日对照表。
- 日历：`make_calendar_events()` 统一生成生日、节日、还款日、订阅续费、工资日、预算锁定、自定义备忘，并自动计算提醒日期。
- 说明：农历节日是演示对照表，不是专业历法库，超出 2026–2027 自动跳过。

### 2. 所有场景共享的区块

每个 A~G 场景现在都包含：

| 区块 | 内容 |
|---|---|
| `cards` | 1 张借记卡 + 1 张信用卡（额度、已用、可用、账单日、还款日、限额、状态） |
| `credit_card_bill` | 本期信用卡账单：明细、合计、最低还款、已还、未还、账单日/还款日、状态 |
| `family` | 1~3 位家庭成员及下一次生日 |
| `calendar_events` | 生日/节日/还款/续费/工资日/预算锁定/备忘，含提醒日期与优先级 |
| `expected_insights` | 智能检测"标准答案"：工资、重复扣款、还款、续费、生日、预算锁定、异常大额消费，均带证据交易 ID |
| `subscriptions` | 仅 E 场景：商户、金额、周期、上次扣费、下次扣费、状态 |

### 3. 场景 G：信用卡与卡片管理

- 生成借记卡流水和信用卡本期消费（信用卡消费独立于存款账户，不影响存款余额对账）。
- 卡片事件随机四选一：提额、下调交易限额、冻结后解冻、挂失后补卡。
- 卡片最终状态、额度、限额必须与最后一条事件一致。
- 有未还账单时，日历必须有对应还款提醒。

### 4. `expected_insights` 的定位

这是**生成时已知的标准答案**，用来评估分析 Agent 的识别准确率；真实运行时分析 Agent 只能看流水自己算。适配层输出时会附带 `evaluation_only_fields: ["expected_insights"]`，提醒消费方不要把它直接展示给客户。

### 5. 校验增强

- 卡片：类型/状态/脱敏卡号/账户引用/额度关系/账单日与还款日。
- 账单：明细合计、已还与未还、最低还款、状态一致性、未还金额与卡片已用额度一致、账单周期顺序。
- 家庭：成员 ID、生日格式、出生年份与年龄一致。
- 订阅：金额、周期、下次扣费日、状态，金额必须与历史扣款一致。
- 日历：事件类型/类别/优先级/状态、提醒日期 = 事件日期 - 提前天数、关联对象必须存在。
- 洞察：类型/严重度/日期，证据交易必须存在，重复扣款至少 2 笔证据。
- 卡片事件：类型、日期、before/after 快照、最终状态/额度/限额与最后一条事件一致。
- 场景 F 新增：锁定金额不能超过账户可用余额。

### 6. 适配层与接口

- `scenario_adapter.py` 支持 G，新增卡片、账单、订阅、日历、卡片事件的整数分转换。
- `_assert_integer_minor` 递归检查所有 `*_minor` 字段，包含嵌套的 `transaction_limit_minor`。
- 账单明细 `amount` 支出为负、退款为正；卡片事件 before/after 快照里的金额也转整数分。
- HTTP 入口无需改动，自动支持 G。

## 测试与验证

```powershell
# 全部测试（73 项）
& "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe" -m unittest discover -s . -p "test_*.py"

# 生成 A~G 标准样例（可复现）
& "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe" main.py --all --seed 42 --reference-date 2026-10-23

# 本地接口
& "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe" scenario_server.py --port 8765
```

最近结果：

- **73 项测试全部通过**；
- A~G 七个场景均生成并保存；
- 稳健性扫描：6 个日期（含月末/年末）× 15 个 seed × A~G = **630 组，0 失败**；
- HTTP：G 场景返回 200，卡片、账单、日历、洞察字段均为契约格式。

## 重要数据规则

- 金额字段非负，方向由 `transaction_type` 表示；对外接口转整数分并附符号 `amount`。
- 信用卡消费独立于存款账户，不参与存款对账；未还金额 = 卡片已用额度。
- `rejected`、`pending` 等未完成交易不改变账户余额。
- 家人生日的 `birthday` 是"下一次生日"，`birth_year` 是出生年份。
- 日历提醒日期 = 事件日期 - `remind_days_before`，必须精确一致。
- 智能洞察的证据交易必须真实存在；重复扣款至少 2 笔证据。
- 所有场景数据均为演示用虚构数据。

## 配套分析模块（已开始）

`C:\Users\111\Desktop\AI_Banking\主任务_金融分析与量化`（原 `quant analysis`）已实现第一版分析内核与集成层（详见该目录 README）：

- `bridge.py`：通过统一契约调用本环境生成 Agent，不复制代码；
- `pipeline.py`：需求 → 场景 → 账单报告 / 异常 / 订阅负担 / 现金流 / 流动性 / 预算建议；
- `tools.py`：9 个主 Agent 工具（只读、JSON、无副作用）；
- 分类 / 月度 / 年度账单报告；
- 9 类异常与提醒识别（重复扣款、失败转账、还款、续费、订阅调价、生日、预算锁定、工资、异常大额消费）；
- 异常大额消费按类别设置门槛（装修 3 万、旅行 2 万、医疗 5 万等），减少一次性大额误报；
- 用 `expected_insights` 当标准答案的评测（A~G 样例 P/R/F1 = 1.0）；
- 26 个扰动/对抗样例，覆盖已知误报点，全部通过（FP 0 / FN 0）；
- 订阅负担率、现金流投影、跨场景流动性、每月可安全储蓄/投资额；
- `make_fixtures.py` 固定 seed 生成可复现样例，115 项测试通过。

### 已接入 FirstAgent（2026-10-24）

`C:\Users\111\Desktop\FirstAgent` 已加入 `first_agent/analysis_bridge.py`：

- 会话账本 → 契约场景（整数分、booked、去 PII）→ 分析工具；
- `POST /api/analysis`、`GET /api/analysis`、`GET /api/analysis/status`；
- `POST /api/scenarios/generate` 通过本目录 `bridge.py` 调用环境生成 Agent；
- `/api/health` 返回 `analysis.available`；
- 分析前后账本余额与版本不变，`ledger_modified=false`；
- FirstAgent 验证：34 项集成测试通过（20 原有 + 14 分析）。

### 2026-10-24 第三轮：演示脚本、对客防泄漏、预算建议

- 新增 `AI_Banking/demo_full_chain.py`：一条命令跑通
  转账 → 账单分析 → 订阅续费 → 生日锁定 → 流动性 → 预算建议；
- `scenario.generate` 默认剥离 `expected_insights` / `evaluation_only_fields`，
  只有 `include_evaluation=true` 才返回；FirstAgent `/api/scenarios/generate` 自动继承；
- 新增只读工具 `budget.advice`：月度结余 + 现金流最低余额 → 每月可安全储蓄/投资额；
- `recommend` 接入预算建议：分析可投上限 > 0 时收紧推荐金额；为 0 时保留原配置
  并提示先补应急金；响应新增 `budget_basis` 标注来源；
- 新增 `backtest_budget.py`：A~G × 6 种压力 × 2 个周期 × 13 种缓冲策略，
  1092 次全部通过；修正跨月工资取数，报告见 `reports/budget_backtest.md`；
- 新增 `organizer.py` 数据整理 Agent：契约场景 → analysis / recommendation /
  cards / display 四视图 + 质量清单，20 项测试通过；
- 主任务测试 93 项、环境生成 73 项、FirstAgent 34 项，全部通过。

### 2026-10-24 第四轮：幂等存储改 SQLite

- `scenario_adapter.py` 的幂等结果从内存字典改为单机 SQLite；
- 默认路径 `环境生成agent/runtime/idempotency.sqlite3`，可用
  `ENV_AGENT_IDEMPOTENCY_DB` 覆盖；`configure_idempotency_store(path)` 供测试切换；
- 表结构 `(session_id, key, params, response, created_at)`，同 key 同参数重放原响应，
  改参返回 `IDEMPOTENCY_CONFLICT`；
- 跨进程重启验证：两次独立进程用同 key 调用，返回相同 `scenario_id`，数据库保留 1 条记录；
- 新增 3 项测试，环境生成测试从 70 项增至 73 项。

## 下一步（从这里继续）

1. ✅ **比赛演示脚本**（2026-10-24 完成）：`AI_Banking/demo_full_chain.py`。
2. ✅ **预算建议**（2026-10-24 完成）：`budget.advice`，储蓄保留 1 个月支出、投资保留 3 个月支出。
3. ✅ **理财推荐接入预算建议**（2026-10-24 完成）：`recommend` 用 `investment.headroom_minor`
   收紧可投金额，为 0 时回退并提示先补应急金，响应 `budget_basis` 可追溯。
4. ✅ **合成场景参数化回测**（2026-10-24 完成）：`backtest_budget.py`，1092 次策略组合全部通过。
5. ✅ **数据整理 Agent**（2026-10-24 完成）：`organizer.py` 四视图 + 质量清单，20 项测试通过。
6. **真实脱敏数据回测**：校准类别阈值、订阅负担分级、锁定比例与 1/3 个月缓冲策略。
7. **把生成逻辑拆到 `scenario_generator.py`**，让 `main.py` 只保留解析、校验编排和保存。
8. ✅ **幂等存储改 SQLite**（2026-10-24 完成）：单机持久化，跨进程重启可重放。

## 面向初学者的协作约定

- 每次聚焦一个小步骤，先读现状再修改。
- 修改后解释规则和运行方式，并运行对应测试。
- 先保留可运行代码，优先通过测试和小范围修改推进。
- 每完成一个关键节点，更新本进度文件。
