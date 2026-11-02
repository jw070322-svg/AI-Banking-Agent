# AI Banking｜数据整理 Agent 逻辑链与接口

> 更新时间：2026-10-24。定位：把「用户环境」整理成各队友模块能直接读取的
> 数据与条件，不新增账本、不新增金额语义、不复制现有转换层。

## 1. 它解决什么问题

现在项目里已经有三条“数据进来”的路径：

| 来源 | 现有转换层 | 输出 |
|---|---|---|
| 环境生成 Agent 的 A~G 场景 | `scenario_adapter.py` | 契约场景 JSON |
| FirstAgent 会话账本 | `first_agent/analysis_bridge.py` | 契约场景 JSON |
| 读取已有文件 | `analysis/loader.py` | 契约场景 JSON |

三条路径最后都汇合到**契约场景**。但各队友模块要的并不是同一份数据：

- 分析/量化要契约场景；
- 推荐模块要 `profile`（风险评估、期限、目标）和 CNY 元的 `budget_cny`；
- 卡管理要卡片、账单、卡片事件；
- UI 要只读展示数据，不能有第二份账本；
- 知识模块不消费客户流水，不应该被喂客户数据。

数据整理 Agent 的职责就是：**以契约场景为唯一输入，投影出各模块可读的视图 +
一份数据质量清单**。它不是第四个转换器，而是转换后的分发层。

## 2. 逻辑链

```text
┌─────────────────────────────────────────────────────────────┐
│ 1. 用户环境                                                  │
│    A. 环境生成 A~G 契约场景                                  │
│    B. FirstAgent 会话账本（先经 analysis_bridge 转契约场景） │
│    C. 未来原始导入（CSV/JSON，预留适配器，本期不做）          │
└───────────────────────────┬─────────────────────────────────┘
                            │ 统一为契约场景（唯一数据边界）
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. 数据整理 Agent（本期新增，只读）                           │
│    输入：契约场景 + 可选上下文（profile/goal/金额/consent）   │
│    校验：金额、状态、日期、重复 ID、PII                       │
│    原则：不改语义、不写账本、不读 expected_insights           │
│    产出：quality manifest + 各模块视图                        │
└───────────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┬─────────────┐
        ▼                   ▼                   ▼             ▼
   analysis 视图      recommendation 视图    cards 视图    display 视图
   契约场景 + 提示     profile + 条件        卡片/账单/事件  只读摘要
        │                   │                   │             │
        ▼                   ▼                   ▼             ▼
   我们的工具/流水线    Ethan 推荐模块        eva/卡管理      vv 界面（只读）
```

知识模块（YUKI）**不接入客户流水**：它负责银行知识检索，客户事实由主 Agent
在回答时引用分析结果，避免把 PII 或客户账本送进 RAG。

## 3. 输入边界与责任划分

| 环节 | 谁负责 | 数据整理 Agent 是否参与 |
|---|---|---|
| 环境生成内部元格式 → 契约 | `scenario_adapter.py` | 不参与，直接吃契约 |
| FirstAgent 会话状态 → 契约 | `analysis_bridge.py` | 不参与，直接吃契约 |
| 契约 → 各模块视图 | **数据整理 Agent** | 负责 |
| 分析计算 | `analysis/` + `tools.py` | 不负责，只提供视图 |
| 写账本/转账 | FirstAgent `service.py` | 不参与，永远只读 |

**关键约束：会话状态不直接喂给整理 Agent。** 先由 FirstAgent 的
`session_to_scenario()` 转成契约场景，再调用整理 Agent。这样不会出现第二套
金额、状态和类别映射。

## 4. 各视图的字段与单位

### 4.1 analysis 视图

- 内容：契约场景本身 + 可用月份、booked 笔数、缺失区块；
- 金额：CNY 整数分；
- 消费方：`tools.call_tool(...)`、`pipeline.run_pipeline(...)`。

### 4.2 recommendation 视图

对齐 `first_agent/vendor/finance/matching_core.py` 的 `user` 字段：

| 字段 | 来源 | 缺失时 |
|---|---|---|
| `user_id` | 场景 `user.user_id` 或上下文 | 允许 `null` |
| `risk_tolerance` | 上下文 profile | `null`，推荐模块返回 `needs_profile_completion` |
| `risk_capacity` | 上下文 profile，缺省 1 | 使用 1，并在 assumptions 说明 |
| `budget_cny` | `min(配置金额, 分析可投上限)` ÷ 100 | 无配置时用分析上限 |
| `horizon_days` | 上下文 goal.months × 30 | 默认 30 |
| `max_redemption_days` | 上下文 profile | 默认 1 |
| `objective` | 上下文 profile | 默认 `liquidity` |
| `preferred_categories` | 上下文 profile | 默认 `["cash"]` |

**单位**：只有这个视图的 `budget_cny` 是 CNY 元，其余金额一律整数分；
视图内显式带 `money_unit`，避免重演“元/分混用”。

可投上限来自 `budget_advice.investment.headroom_minor`，与 FirstAgent 当前
推荐逻辑一致：上限为 0 时回退到配置金额，并保留提示，不静默清空推荐。

### 4.3 cards 视图

- 内容：`cards`、`credit_card_bill`、`card_events`；
- 金额：整数分；
- 附带 `available` 和 `missing`，没有数据时明确标记，不编造卡状态；
- 消费方：eva 的卡管理/风控（数据层），未来 FirstAgent 卡操作接入。

### 4.4 display 视图（可选）

- 内容：账户余额、最新月收入/消费、订阅数量、卡片数量；
- 金额：整数分；
- 明确 `read_only=true`、`ledger_modified=false`；
- 不包含 consent、操作状态、待确认操作，**不是账本快照**；
- 消费方：vv 做只读展示；实时会话仍以 `/api/snapshot` 为准。

## 5. 质量清单 manifest

每个整理结果都带：

```json
{
  "organizer_version": "1.0.0",
  "contract_schema_version": "1.0.0",
  "source": "contract_scenario",
  "currency": "CNY",
  "amount_unit": "minor",
  "available_views": ["analysis", "recommendation", "cards", "display"],
  "missing_blocks": ["family", "calendar_events"],
  "quality": {
    "transaction_count": 13,
    "booked_count": 13,
    "duplicate_transaction_ids": [],
    "invalid_amount_count": 0,
    "missing_categories": [],
    "pii_fields_removed": [],
    "low_spending": false,
    "has_income": true
  },
  "assumptions": [],
  "warnings": [],
  "ledger_modified": false,
  "simulated": true
}
```

质量清单只做**结构性检查**，不重复异常识别逻辑；重复扣款、异常大额等仍由
`analysis/anomaly.py` 负责。

## 6. 与现有模型的冲突规避

1. **不新建账本**：整理 Agent 无状态、纯函数，输出 `ledger_modified=false`；
2. **不新建金额单位**：内部一律整数分，只有 recommendation 视图显式转 CNY 元；
3. **不复制转换**：会话→契约仍由 `analysis_bridge.py`，生成→契约仍由
   `scenario_adapter.py`；
4. **不复制识别规则**：质量清单只查结构，不做异常判定；
5. **不输出标准答案**：读取时忽略 `expected_insights`，输出中不出现；
6. **不编造缺失条件**：风险档案、目标、授权缺失就标记，交给下游模块拒绝或澄清；
7. **不写 UI 状态**：display 只是派生只读摘要，实时 UI 仍读 `/api/snapshot`；
8. **不做分布式幂等**：整理是纯函数；需要幂等的场景生成仍走 SQLite 那套。

## 7. 版本与兼容

- `ORGANIZER_VERSION` 独立于契约版本；
- 输入契约不变时，整理 Agent 的输出字段只增不改；
- 新增视图必须写进 `available_views` 和 README；
- 下游模块按视图名读取，不按字段顺序或缺失位置猜测。

## 8. 本期实现范围

- 核心：`organizer.py` 的 `organize(scenario, context)`；
- 视图：analysis / recommendation / cards / display + manifest；
- CLI：`python organizer.py --input ... --context ... --out-dir ...`；
- 测试：单位换算、缺失条件、PII、重复 ID、输入不被修改、标准答案不泄漏；
- **不做**：原始 CSV/Excel 导入、卡操作写入、推荐产品目录、UI 状态写回。

## 9. 当前实现状态（2026-10-24）

已实现：

| 文件 | 用途 |
|---|---|
| `主任务_金融分析与量化/organizer.py` | `organize(scenario, context)` + CLI + 文件输出 |
| `主任务_金融分析与量化/tests/test_organizer.py` | 22 项测试：视图、单位、缺失条件、PII、标准答案、输入不变、工具消费 |
| `主任务_金融分析与量化/README.md` | 用法与边界 |

命令：

```powershell
cd 主任务_金融分析与量化
& "$env:LOCALAPPDATA\Programs\Python\Python315\python.exe" organizer.py `
  --input fixtures/SCENARIO_F.json --out-dir organized
```

验证：主任务 115 项测试全部通过；F 场景整理后
`recommendation.profile.budget_cny = 10835.68`，`budget_source =
analysis_headroom`；G 场景 cards 视图可用；缺失风险档案时
`risk_tolerance=null` 并提示 `needs_profile_completion`。

下一步（可选）：把 `organize` 包装成只读工具 `data.organize`，加入
FirstAgent 的 `/api/analysis` 白名单；本期先保持 CLI/纯函数，避免再改接口。
