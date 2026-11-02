# AI Banking｜主任务：金融分析与量化

按分工，本目录负责**金融数据分析、量化与模型实现**，并负责把环境生成 Agent 与分析
内核串成完整链路。当前实现比赛大纲里的"账单分析""订阅/代扣管理""跨场景联动"三块
的数据与模型支撑。

```text
自然语言需求
    ↓  bridge.generate_scenario()        （调用 ../环境生成agent）
契约场景 JSON（整数分、booked、ledger_modified=false）
    ↓  pipeline.run_pipeline() / analysis/*
账单报告 / 异常提醒 / 订阅负担 / 现金流 / 流动性
    ↓  tools.call_tool()
主 Agent 可调用的工具结果
```

## 目录

```text
主任务_金融分析与量化/
├── analysis/
│   ├── data.py        # 统一数据视图（金额整数分、booked、消费口径）
│   ├── aggregate.py   # 分类 / 月度 / 年度汇总与报告
│   ├── anomaly.py     # 异常与提醒识别（含类别阈值、订阅调价）
│   ├── cashflow.py    # 订阅负担 + 现金流投影
│   ├── liquidity.py   # 锁定预算后的可用流动性
│   ├── evaluate.py    # 与标准答案对比，计算 P/R/F1
│   ├── loader.py      # 读取契约 JSON / 环境生成内部 JSON / HTTP 响应
│   └── __init__.py
├── bridge.py          # 主任务 ↔ 环境生成 Agent 的桥（契约边界）
├── pipeline.py        # 端到端流水线
├── tools.py           # 主 Agent 工具清单与调用入口
├── perturbations.py   # 扰动/对抗样例
├── tests/             # 单元测试 + 端到端评测
├── fixtures/          # 由 make_fixtures.py 生成（A~G 七份契约样例）
├── make_fixtures.py   # 调用环境生成 Agent 生成固定样例
├── cli.py             # 命令行入口
└── README.md
```

## 快速开始

在本目录下执行：

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe"

# 1) 生成可复现样例（调用 ../环境生成agent）
& $py make_fixtures.py --seed 42 --reference-date 2026-10-23

# 2) 某月账单报告 + 异常提醒
& $py cli.py report fixtures/SCENARIO_C.json --month 2026-10

# 3) 用标准答案评估识别效果
& $py cli.py evaluate fixtures

# 4) 运行扰动/对抗样例，检查误报
& $py cli.py perturb

# 5) 订阅负担 + 未来 30/90 天现金流 + 锁定预算后的可用流动性
& $py cli.py cashflow fixtures/SCENARIO_E.json --days 30
& $py cli.py cashflow fixtures/SCENARIO_F.json --days 90

# 6) 端到端：需求 → 环境生成 → 分析
& $py cli.py pipeline --prompt "配偶生日，锁定 1000 元预算" --scenario-type F --seed 42 --reference-date 2026-10-23 --days 30
& $py cli.py pipeline --file fixtures/SCENARIO_C.json --days 30 --json

# 7) 主 Agent 工具
& $py cli.py tools --list
& $py cli.py tools --call anomalies.detect --file fixtures/SCENARIO_C.json
& $py cli.py tools --call analysis.pipeline --file fixtures/SCENARIO_F.json --args '{\"days\": 30}'

# 8) 全部测试
& $py -m unittest discover -s . -p "test_*.py"
```

## 与环境生成 Agent 的协作边界

- 环境生成 Agent 位于 `../环境生成agent`，是独立维护的模块，**不复制代码**；
- 双方只通过 **契约场景 JSON** 通信（整数分、booked、ledger_modified=false）；
- `bridge.py` 负责导入与调用；环境不可用时返回 `ENVIRONMENT_UNAVAILABLE`，不影响纯分析功能；
- 环境生成侧升级只要契约不变，本目录无需修改。

自检：

```python
from bridge import environment_status
environment_status()   # {"available": True, "scenario_types": [...], ...}
```

## 主 Agent 工具接口

主服务（王语嫣负责的 backend）只需要：

```python
from tools import list_tools, call_tool

result = call_tool("anomalies.detect", {}, data=session_scenario)
```

- 工具清单：`list_tools()`，含 JSON Schema 参数；
- 9 个工具：`scenario.generate`、`bills.summary`、`bills.categories`、
  `anomalies.detect`、`subscriptions.burden`、`cashflow.project`、
  `liquidity.available`、`budget.advice`、`analysis.pipeline`；
- 全部只读、无副作用，响应固定包含 `simulated=true`、`ledger_modified=false`；
- 参数错误、缺少上下文、环境不可用都以 `status=rejected` + `error.code` 返回，不抛异常；
- `expected_insights` 只在 `analysis.pipeline` 的 `include_evaluation=true` 时使用，
  避免对客回答"抄标准答案"。
- `scenario.generate` 默认就不返回 `expected_insights` / `evaluation_only_fields`；
  只有显式传 `include_evaluation=true` 才保留，供评测脚本使用。

## 数据整理 Agent（多模块视图）

`organizer.py` 把契约场景投影成各队友模块能直接读取的数据与条件。它不是第四个
转换器：会话账本 → 契约仍由 FirstAgent 的 `analysis_bridge.py` 负责，环境生成
内部格式 → 契约仍由 `scenario_adapter.py` 负责。

```text
契约场景（唯一输入）
  → organize(scenario, context)
      ├─ analysis：契约场景 + 月份/缺失区块
      ├─ recommendation：profile + 金额条件（budget_cny 为 CNY 元）
      ├─ cards：卡片 / 信用卡账单 / 卡片事件
      ├─ display：只读展示摘要
      └─ manifest：质量检查、假设、警告
```

运行：

```powershell
& $py organizer.py --input fixtures/SCENARIO_F.json --out-dir organized
& $py organizer.py --input fixtures/SCENARIO_G.json --context context.json
```

上下文文件可选，字段示例：

```json
{
  "source": "generated_scenario_F",
  "profile": {
    "risk_tolerance": 1,
    "risk_capacity": 1,
    "objective": "liquidity",
    "preferred_categories": ["cash"],
    "max_redemption_days": 1
  },
  "goal": {"months": 6},
  "configured_amount_minor": 364000,
  "consent": {"read": true, "subscriptions": true, "trade": false}
}
```

输出 6 个文件：`package.json`、`analysis.scenario.json`、
`recommendation.profile.json`、`cards.view.json`、`display.view.json`、
`manifest.json`。

关键约束：

- 只读、无状态，`ledger_modified=false`；
- 金额内部一律整数分，只有 `recommendation.profile.budget_cny` 是 CNY 元；
- 缺失风险档案时 `risk_tolerance=null`，交给推荐模块返回
  `needs_profile_completion`，不编造；
- 默认移除 `expected_insights` / `evaluation_only_fields`，评测时显式
  `include_evaluation=true`；
- 不生成 UI 状态，`display` 只是派生摘要，实时界面仍读 `/api/snapshot`；
- 知识模块不消费客户流水，整理 Agent 不为 RAG 生成客户数据视图。

设计说明见 [数据整理Agent_逻辑链与接口.md](../数据整理Agent_逻辑链与接口.md)。

## 已接入 FirstAgent

`C:\Users\111\Desktop\FirstAgent` 已集成本目录（2026-10-24）：

- `first_agent/analysis_bridge.py`：把持久化会话账本转换成契约场景，再调用 `tools.call_tool`；
- `POST /api/analysis` / `GET /api/analysis`：8 个只读分析工具；
- `POST /api/scenarios/generate`：通过本目录的 `bridge.py` 调用环境生成 Agent；
- `recommend`：授权 `read` 后用 `budget.advice.investment.headroom_minor` 收紧推荐金额，
  响应 `budget_basis` 标注来源；建议为 0 时保留配置金额并提示先补应急金；
- `/api/health` 增加 `analysis.available` 自检；
- 会话内分析前后账本余额与版本不变，响应恒为 `ledger_modified=false`。

FirstAgent 默认从 `../AI_Banking/主任务_金融分析与量化` 导入本模块，也可用
`AI_BANKING_ANALYSIS_DIR` 指定其他位置。权限仍由 FirstAgent 的 `consent.read` 控制。

### 全链路演示（比赛现场）

在 `AI_Banking` 目录执行一条命令：

```powershell
& $py ..\demo_full_chain.py
```

依次演示：授权 → 转账（预览/确认/回执）→ 账单分析 → 订阅续费 →
F 场景生日预算锁定与流动性 → 只读性校验。脚本还会把 `expected_insights`
删掉重跑一次，确认分析结果不变，证明没有"抄标准答案"。退出码 0 表示全部通过。

## 数据口径（与 API-CONTRACT 1.0.0 一致）

- 金额一律 **CNY 整数分**；
- 只统计 `status == booked` 的交易；
- 消费 = 借记卡 `expense` + 信用卡账单 `expense`，退款按负数冲减；
- 转账（`transfer_out`）不是消费，单独统计；
- 收入只算 `income` 类型，退款不重复计收入；
- 信用卡消费不影响存款账户余额，但计入账单分析。

## 模块 API

```python
from analysis import (
    load_scenario, monthly_report, annual_report, overall_summary,
    category_breakdown, detect_anomalies, evaluate_detection,
)

data = load_scenario("fixtures/SCENARIO_A.json")
monthly_report(data, "2026-10")      # 月度报告
annual_report(data, 2026)            # 年度报告
category_breakdown(data, month="2026-10")
detect_anomalies(data)               # 异常与提醒列表
evaluate_detection(data)             # {"summary": ..., "by_type": ..., "missed": ..., "false_positives": ...}
```

## 识别类型

| 类型 | 规则 | 严重度 |
|---|---|---|
| `duplicate_charge` | 同商户 + 同金额 + 同日出现 ≥2 笔已入账扣款 | 10 分钟内聚簇 high；缺时间 medium；相隔很久不报 |
| `failed_transfer` | 被拒绝/失败的转账 | high |
| `upcoming_bill` | 信用卡有未还金额 | 7 天内或逾期 high，否则 medium |
| `subscription_renewal` | active 订阅有下次扣费日 | 3 天内 high，否则 medium |
| `subscription_price_change` | 订阅最近两次扣款变化 >1% 且 >1 元 | 涨价 high / 降价 medium |
| `birthday_upcoming` | 家庭成员下一次生日 | 30 天内 high / 90 天内 medium / 其余 low |
| `budget_lock` | 生日活动预算已锁定 | medium |
| `salary_detected` | 最近一笔工资收入 | low |
| `unusual_spending` | 借记卡单笔超过**类别门槛**且 > 平均支出倍数，排除固定月度支出 | medium |

### 重复扣款的抗误报设计

- 同一商户、同一金额、同一天只是前提；
- 如果所有交易都有时间：按 **10 分钟窗口聚簇**，只有同一簇 ≥2 笔才报 high；
  上午一杯、下午一杯同样的咖啡不会报；
- 缺少时间时给 medium 提示，由用户确认；
- 退款、被拒绝交易不参与判断。

### 异常大额消费的抗误报设计

- 至少 3 笔支出才计算；
- 单笔金额必须超过**类别门槛**，并且 > 平均支出 × 类别倍数；
- 同一商户在 ≥2 个月出现且金额在 ±10% 内（房租、学费、物业费），视为固定支出，不报。

| 类别 | 最低关注金额 | 相对平均倍数 |
|---|---|---|
| 默认（餐饮/交通/购物/娱乐/日用/通讯等） | 1000 元 | 4× |
| 家居 / 保险 / 旅行 | 20000 元 | 6× |
| 居住 / 装修 | 30000 元 | 6× |
| 医疗 / 教育 | 50000 元 | 6× |

类别表在 `analysis/anomaly.py` 的 `CATEGORY_UNUSUAL_RULES`，是可调策略而不是监管规则。

## 扰动样例（误报防护）

`perturbations.py` 手工构造 21 个最小场景，每个都带"应该报 / 不应该报"的标准答案：

| 类别 | 样例数 | 覆盖 |
|---|---|---|
| 重复扣款（应报） | 4 | 2 分钟内、3 笔连续、无时间、信用卡重复 |
| 重复扣款（不应报） | 7 | 相隔半天、跨日、差 1 分、不同商户、退款配对、被拒交易、每日固定消费 |
| 异常大额消费（应报） | 3 | 单笔远超平均、一次性大额、极端医疗支出 |
| 异常大额消费（不应报） | 8 | 房租、物业费波动、未达门槛、样本不足、5000 元家电、装修、旅行、医疗 30000 元 |
| 订阅调价（应报） | 2 | 涨价、降价 |
| 订阅调价（不应报） | 2 | 金额不变、1 元内波动 |

当前结果：**26/26 通过，FP 0，FN 0**。

## 订阅负担与现金流投影

### 订阅负担 `subscription_burden(data)`

- 月均支出：月付 ×1、季付 ÷3、年付 ÷12，四舍五入到分；
- 占收入比 = 月均订阅 / 最近一次工资；
- 分级（原型约定，不是监管标准）：< 3% low，3%~8% medium，≥ 8% high；
- 输出 7 天 / 30 天内即将扣费金额、每个订阅的下次扣费日与剩余天数；
- 没有工资数据时，比率与等级返回 `null`，不编造分母。

### 现金流投影 `project_cashflow(data, days, today=None)`

从账户当前余额出发，推演未来 N 天（1~366）的余额变化：

| 事件 | 口径 |
|---|---|
| 工资收入 | 从最近一次工资流水取"每月几号 + 金额"，按同样日期重复 |
| 信用卡还款 | 取 `credit_card_bill.outstanding_amount_minor`，还款日已过则按今天支付并给警告 |
| 订阅续费 | 从 `subscriptions.next_charge_date` 起，按 cycle 重复到期末 |
| 生日活动 | `activity_calendar` 中 planned 的鲜花/蛋糕/晚餐预算 |

输出：期初余额、预计收入、计划支出、期末余额、最低余额及其日期、缺口日期、逐笔事件（含事件后余额）、警告。

**这不是收益预测**，是确定性推演，有三个明确假设：

1. 除工资外没有新的收入；
2. 除已知账单/订阅/活动外没有新的支出；
3. 同一天先扣支出、再进收入，最低余额口径偏保守。

因此它适合回答"按现在的安排会不会不够钱"，不适合预测真实消费。

### 跨场景流动性 `available_liquidity(data, days, today=None)`

在现金流投影之上回答比赛"跨场景联动"的问题：生日当月锁定预算后，还能动用多少资金。

- `reserved_remaining_minor`：锁定金额 - 已计划的生日活动支出，剩下的仍需保留；
- `safe_to_spend_now_minor`：**不考虑未来工资**时，现在可以自由动用的金额；
- `safe_to_spend_horizon_minor`：把未来 N 天工资也算进来后的安全上限；
- `locked_amount_at_risk_minor`：未来最低余额低于预留金额的部分，大于 0 说明锁定预算会被日常支出挤占；
- 锁定月份已经结束时，自动释放预留（`lock_active=false`）。

示例（F 场景，30 天）：

```text
当前余额 ¥22,476.59   锁定 ¥1,000.00   已计划活动 ¥790.02
剩余预留 ¥209.98      最低余额 ¥19,913.57
现在可动用 ¥19,703.59 计入未来工资后 ¥19,703.59
锁定预算被挤占 ¥0.00
```

### 预算建议 `budget_advice(data, days, month=None)`

回答"每月最多能拿出多少钱储蓄/投资，而不会让现金流断档"。计算顺序：

```text
月度结余 = 当月收入 - 消费 - 转出
        ↓  取 min(结余, 流动性折算额度)
可安全储蓄 = 保留 1 个月支出的活期缓冲
可安全投资 = 保留 3 个月支出的应急金
```

- 流动性基数用 `available_liquidity` 的 `buffer_after_reserve_minor`，已经扣掉生日锁定预算；
- 投影期内可用额度按 `×30 ÷ days` 折算成每月金额；
- 投影出现缺口、缺少收入数据时直接给 0，并返回 `recommended_action`；
- 输出 `savings` / `investment` 两组金额与 `binding_constraint`（到底是被月度结余还是流动性卡住）；
- `investment.headroom_minor` 是**一次性可投上限**（扣掉 3 个月应急金和生日预留后的余额），
  `safe_monthly_minor` 是**每月建议上限**；分别回答接口里 `capacity` 类问题和月度储蓄问题，
  但公式是本模块自己的策略，不改变 vv 引擎原有语义；
- 1 个月 / 3 个月是**原型策略**，集中在 `analysis/budget.py` 顶部，可按业务调整。

示例（F 场景，30 天）：

```text
月度结余 ¥14,585.20
储蓄建议 ¥14,585.20/月（保留 1 个月支出，受限于月度结余）
投资建议 ¥10,835.68/月（保留 3 个月支出，受限于流动性缓冲）
```

### 参数化回测 `backtest_budget.py`

没有真实脱敏流水时，用 A~G 场景 + 压力变体验证缓冲策略是否稳定：

```powershell
& $py backtest_budget.py
```

- 7 个场景 × 6 种压力（基准 / 支出 +20% / 收入 -20% / 余额 -30% / 组合 / 余额≈0）
  × 2 个周期（30、90 天）× 13 种缓冲策略；
- 输出 `reports/budget_backtest.json`、原始报告 `.md`、规则稳定性报告
  `_rule_stability.md`、数据边界报告 `_data_boundaries.md`；
- 每次调用都检查：金额非负、不超过结余与流动性上限、投资不高于储蓄、
  缺口时建议为 0、输入场景未被修改；
- 当前结果：1092 次全部通过。投资缓冲 1 → 3 → 6 个月时，正投案例占比
  81.0% → 66.7% → 38.1%，说明策略越保守，可投金额下降得越快；
- 同时标注数据质量问题：E 场景支出不足收入的 10%，会标记 `low_spending`，
  提醒不要直接把“高可投额”当成真实结论。

回测还发现并修正了一个取数口径问题：C 场景工资在 9 月、支出在 10 月，
收入改为取“统计月份收入”和“最近一笔工资”的较大值，避免跨月发薪被误判为无收入。

## 关于 100% 指标

- `fixtures/` 由同一个环境生成 Agent 生成，规则口径与识别器一致，所以 A~G 评测是 100%；
  这只证明"数据链路和规则实现一致"。
- `perturbations.py` 是针对已知误报点手工设计的反例，用来防止回归；它也不是真实用户样本。
- 上线前还需要真实脱敏数据的回测，当前不能宣称"真实场景准确率 100%"。

## 下一步

1. ✅ 预算建议（2026-10-24）：`budget.advice` / `budget_advice()`，输出每月可安全储蓄与投资额。
2. ✅ `expected_insights` 已从对客链路剔除：`scenario.generate` 默认剥离，评测开关显式开启才返回。
3. 真实脱敏数据回测，校准订阅负担分级、锁定比例、类别阈值与 1/3 个月缓冲策略。
4. ✅ 分析能力已包装成 9 个只读工具并接入 FirstAgent `/api/analysis`；后续按需补 RPC 别名。
5. 引入滚动中位数/分位数替代平均值，进一步降低样本噪声。
