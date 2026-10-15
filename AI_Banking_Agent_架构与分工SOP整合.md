# 2026 FinTechathon —— AI Banking Agent 项目架构与团队分工方案

> **项目定位：参赛项目设计文档 / Project Architecture v1.1**
>
> 本方案基于 2026 FinTechathon 官方赛事海报整理，围绕 **AI Banking、金融业务场景、AI Agent、金融数据、风险控制与合规** 展开设计。
>
> **分工基准**：总体架构、Agent 与各部分把关由 wzy 负责；Agent 代码、Tools、Database 与后端由王语嫣负责；金融数据分析、量化、模型实现及环境生成 Agent 搭建由袁爱岑负责；Dashboard、UI、聊天模块与可视化由谢涵微负责；知识库、RAG、测试与 Feedback 由杨婧柔负责。附加材料中，答辩 PPT 由杨婧柔负责，技术文档由王语嫣负责，安全自评由谢涵微负责。
>
> **文档结构**：第一部分为项目分析与用例设计；第二部分为系统架构与模块分工；第三部分为团队组建、协作流程与项目落地；第四部分为面向「1 个大二 + 4 个大一」团队的优化分工方案（本团队实际分工以《Agent 大赛分工》的安排为准，并在第四部分匹配落实）。
>
> [此处建议补充：2026 FinTechathon 官方赛事要求的关键信息（赛题原文、评分标准、作品提交截止时间）；并核对共享链接 https://chatgpt.com/share/6abf45d8-1e88-83e8-91d9-22e474a77b9c 中的内容是否对本文档有新增或更正]

---

## 第一部分：项目分析与用例设计

### 1.1 首先明确：比赛要求的不是一个普通 Chatbot

从官方海报的「赛题说明」以及其中明确出现的 **「AI Banking」** 可以判断，项目的核心应当是把 AI 能力嵌入银行业务流程，而不是单纯做一个金融问答机器人。

三个层次可以这样区分：

```text
普通 Chatbot
User
 ↓
LLM
 ↓
Answer
```

```text
金融 AI Assistant
User
 ↓
LLM
 ↓
Financial Answer
```

真正应该参赛的 AI Banking Agent：

```text
User
 ↓
Intent Understanding
 ↓
Planning
 ↓
Financial Data
 ↓
Tool Calling
 ↓
Financial Analysis
 ↓
Risk / Compliance
 ↓
User Confirmation
 ↓
Execution
 ↓
Monitoring
```

因此：

$$
AI\ Banking\ Agent = LLM + Financial\ Data + Tools + Financial\ Intelligence + Risk + Compliance + Execution
$$

### 1.2 从银行业务角度拆解 AI Banking

一个完整的 AI Banking Agent 可以拆成：

```text
AI Banking
│
├── ① 智能客户服务
├── ② 个人财务管理
├── ③ 金融分析与决策支持
├── ④ 金融产品匹配
├── ⑤ 风险管理
├── ⑥ 智能营销 / 个性化服务
├── ⑦ 银行业务执行
└── ⑧ 安全与合规
```

最容易做成普通 Chatbot 的是智能客服；真正能够体现 Agent 技术含量的是：

> **理解需求 → 获取数据 → 分析 → 调用工具 → 决策支持 → 风险检查 → 执行 → 持续监控。**

### 1.3 Use Case ①：AI Banking 智能客户服务

用户可以通过自然语言提出：

- 「帮我查一下最近三个月的消费。」
- 「为什么我这个月花的钱特别多？」
- 「我的银行卡为什么扣了这笔钱？」
- 「帮我看看我的账户情况。」
- 「我要办理某项银行业务，需要什么材料？」

系统需要：

```text
User Query
     ↓
Intent Detection
     ↓
Entity Extraction
     ↓
Context Understanding
     ↓
Knowledge Retrieval
     ↓
Tool Calling
     ↓
Response
```

需要的技术：

- LLM
- NLP
- Intent Classification
- Entity Recognition
- RAG
- Function Calling
- Conversation Memory

### 1.4 Use Case ②：Personal Financial Management（个人财务管理）

建议重点开发个人财务管理。

用户：

> 「我每个月工资 15,000，但是为什么总是存不下来？」

Agent 不应该简单回答「建议减少消费」，而应该真正分析数据。

#### Financial Data Pipeline

```text
Bank Transactions
       ↓
Data Cleaning
       ↓
Transaction Classification
       ↓
Income / Expense Analysis
       ↓
Cash Flow Analysis
       ↓
Financial Profile
```

例如（以月收入 ¥15,000 为例）：

| Category | Monthly Amount | % of Income |
|---|---:|---:|
| Rent | ¥5,000 | 33.3% |
| Food | ¥2,300 | 15.3% |
| Shopping | ¥2,800 | 18.7% |
| Transport | ¥1,000 | 6.7% |
| Other | ¥2,100 | 14.0% |
| **Savings** | **¥1,800** | **12.0%** |

Agent 可以进一步发现：

```text
Income
+5%

Expense
+16%

Savings
-18%
```

从而得到由数据支持的解释：

> 用户储蓄率下降主要来自可选消费增长，而不是收入下降。

### 1.5 Use Case ③：Financial Intelligence（金融智能）

不能让 LLM 自己完成复杂金融计算，应采用：

```text
LLM
 ↓
提出分析任务
 ↓
Quant Engine
 ↓
数学计算
 ↓
结构化结果
 ↓
LLM解释
```

#### Cash Flow

$$
CF_t=Income_t-Expense_t
$$

#### Saving Rate

$$
SR_t=\frac{Income_t-Expense_t}{Income_t}
$$

#### Liquidity

$$
LR=\frac{Liquid\ Assets}{Expected\ Short\text{-}Term\ Obligations}
$$

#### Debt Burden

$$
DBR=\frac{Monthly\ Debt\ Payment}{Monthly\ Income}
$$

#### Portfolio Risk

$$
\sigma_p^2=w^T\Sigma w
$$

还可以加入：

- Expected Return
- Volatility
- Sharpe Ratio
- Maximum Drawdown
- VaR
- Scenario Analysis
- Cash Flow Forecast

这样项目形成：

> **LLM + Agent + Quantitative Finance**

### 1.6 Use Case ④：金融产品匹配

用户：

> 「我有 100,000 元，未来半年不用，希望流动性比较高。」

Agent 应该：

```text
User Requirement
       ↓
Requirement Parser
       ↓
Risk / Liquidity Profile
       ↓
Product Database
       ↓
Product Screening
       ↓
Quantitative Comparison
       ↓
Compliance Check
       ↓
Explainable Output
```

而不是：

```text
User
 ↓
LLM
 ↓
“我推荐产品 A”
```

建议建立 Product Matching Engine。

输入：

```text
Amount
Time Horizon
Liquidity Requirement
Risk Tolerance
Financial Goal
```

输出：

```text
Product A
Product B
Product C
```

比较：

| 指标 | 产品 A | 产品 B | 产品 C |
|---|---|---|---|
| 风险特征 | … | … | … |
| 流动性 | … | … | … |
| 期限 | … | … | … |
| 收益特征 | … | … | … |
| 适配条件 | … | … | … |

最终由 Agent 解释差异，而不是让 LLM 凭记忆生成金融产品信息。

### 1.7 Use Case ⑤：Risk Management（风险管理）

银行场景和普通 AI 最大的区别之一是：

> **AI 不应该什么都做。**

因此需要独立 Risk Engine。

```text
Agent Request
      ↓
Risk Engine
      ↓
┌──────────────────┐
│ Permission Check │
│ Risk Check       │
│ Compliance Check │
│ Fraud Check      │
│ Data Check       │
└────────┬─────────┘
         ↓
    Decision
```

结果可以是：

```text
LOW RISK
→ Agent handles

MEDIUM RISK
→ User confirmation

HIGH RISK
→ Human review
```

### 1.8 Use Case ⑥：Compliance（合规）

金融 Agent 的重要风险是：

> **LLM 说得很像真的，但实际上不一定正确。**

因此：

```text
LLM Output
     ↓
Compliance Guard
     ↓
Rule Engine
     ↓
Fact Verification
     ↓
Risk Disclosure
     ↓
Final Response
```

需要重点控制：

- 虚构金融产品
- 虚构收益
- 未经授权的数据访问
- 超权限操作
- 不恰当金融建议
- 缺失风险提示
- 敏感信息泄露
- Prompt Injection

### 1.9 Use Case ⑦：真正的 Agent Action

Agent 和 Chatbot 最大的区别：

> **Agent 可以行动。**

例如：

> 「帮我制定下个月预算。」

Agent：

```text
① 获取历史交易
② 分析收入
③ 分析消费
④ 预测固定支出
⑤ 生成预算
⑥ 用户确认
⑦ 创建预算
⑧ 持续监控
```

形成：

```text
Budget Created
       ↓
Monthly Monitoring
       ↓
Overspending Alert
       ↓
AI Explanation
```

### 1.10 核心技术挑战

| 问题 | 对应技术 |
|---|---|
| 用户说了什么？ | NLP / LLM |
| 用户真正想干什么？ | Intent Detection |
| 用户的数据是什么？ | Data Engineering |
| 应该怎么算？ | Quant Model |
| 应该调用什么？ | Tool Calling |
| 应该查什么资料？ | RAG |
| 能不能执行？ | Authorization |
| 是否存在金融风险？ | Risk Engine |
| 是否合规？ | Compliance Engine |
| AI 为什么这么判断？ | Explainability |
| 如何真正执行？ | Backend / API |
| 如何防止攻击？ | Security |
| 如何验证 AI？ | QA / Evaluation |
| 如何让评委看到？ | Frontend |

---

## 第二部分：系统架构与模块分工

### 2.1 总体系统架构

```text
                         ┌──────────────────────┐
                         │      USER / UI       │
                         │ Web / Mobile / Chat  │
                         └───────────┬──────────┘
                                     │
                                     ▼
                         ┌──────────────────────┐
                         │ Conversation Layer   │
                         │ Dialogue Management   │
                         └───────────┬──────────┘
                                     │
                                     ▼
                 ┌──────────────────────────────────┐
                 │       AI BANKING AGENT            │
                 │                                  │
                 │ Intent / Planning / Memory       │
                 │ Reasoning / Tool Selection       │
                 └───────────────┬──────────────────┘
                                 │
             ┌───────────────────┼───────────────────┐
             │                   │                   │
             ▼                   ▼                   ▼
      ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
      │ Financial    │   │ Financial     │   │ Tool Calling │
      │ Data Engine  │   │ Intelligence  │   │    Engine    │
      └──────┬───────┘   └───────┬───────┘   └──────┬───────┘
             │                   │                   │
             ▼                   ▼                   ▼
      Transaction DB       Quant Models        Banking APIs
      User Profile         Risk Models         Product APIs
      Account Data         Forecasting         Search / RAG
      Portfolio            Scoring             Calculators
             │                   │                   │
             └───────────────────┼───────────────────┘
                                 ▼
                     ┌──────────────────────┐
                     │ Risk & Compliance    │
                     │       Guard          │
                     └──────────┬───────────┘
                                │
                   ┌────────────┴────────────┐
                   ▼                         ▼
             Human Review                Execution
                   │                         │
                   └────────────┬────────────┘
                                ▼
                     ┌──────────────────────┐
                     │ Audit & Monitoring    │
                     └──────────────────────┘
```

#### 架构交付与调用路径

- **[新增] 架构图：wzy 主责，王语嫣、袁爱岑、谢涵微、杨婧柔提供各自模块信息**。展示交互层、Action Agent、数据与数字孪生、模拟、RAG、工具网关、Guardian、业务适配器和审计；明确调用前校验、确认、执行及回执更新路径，图中模块必须对应提交代码。

交互层提出需求，Action Agent 负责编排；金融数据与数字孪生、情景模拟、RAG 提供分析和证据。工具网关与 Guardian 在调用前进行校验，需要确认的操作完成确认后，执行前再复核，由业务适配器执行，依据回执更新审计与业务状态。

### 2.2 Module 1 —— Frontend / Banking Copilot

负责：

- Chat Interface
- Financial Dashboard
- Account Overview
- Cash Flow Visualization
- Risk Visualization
- AI Recommendations
- User Confirmation
- Agent Action Timeline

#### 推荐 UI

```text
┌────────────────────────────────────────────┐
│              AI BANKING                   │
├───────────────┬────────────────────────────┤
│ Financial     │ AI Banking Assistant       │
│ Dashboard     │                            │
│               │ User:                      │
│ Balance       │ “分析我的消费。”          │
│ ¥XX,XXX       │                            │
│               │ AI:                        │
│ Cash Flow     │ 正在分析过去6个月交易...   │
│ +¥X,XXX       │                            │
│               │ ┌──────────────────────┐   │
│ Risk          │ │ Financial Analysis   │   │
│ Medium        │ │ Food       18%       │   │
│               │ │ Shopping   22%       │   │
│               │ │ Rent       31%       │   │
│               │ └──────────────────────┘   │
└───────────────┴────────────────────────────┘
```

#### 负责人

**谢涵微（Frontend Engineer / UI Designer）**

#### 实施与验收要求

- **前端与可视化：谢涵微主责**。交付对话、仪表盘、方案比较、确认卡、任务时间线与实际回执，所有关键数字读取后端结果。

- **[新增] 前端与确认流程测试：谢涵微主责，杨婧柔纳入统一报告**。覆盖金额与单位一致、参数修改后重新确认、候选收款人选择、部分成功、未知状态及真实事件驱动的进度显示。

### 2.3 Module 2 —— Agent Orchestrator（Agent协调器、统筹者）

核心流程：

```text
User Input
    ↓
Intent
    ↓
Plan
    ↓
Tool Selection
    ↓
Tool Execution
    ↓
Result Verification
    ↓
Response
```

例如：

> 「为什么我最近存不下钱？」

Agent 自动形成：

```text
Task Plan

1. 获取过去6个月交易
2. 分类交易
3. 计算收入变化
4. 计算支出变化
5. 识别主要消费类别
6. 计算储蓄率
7. 找出异常变化
8. 生成分析
9. Verify
10. 返回结果
```

#### 负责人

**wzy 主责总体 Agent 架构、编排与各部分把关；王语嫣负责 Agent 代码搭建、工具及后端实现。**

技能：

- LLM
- Prompt Engineering
- Function Calling
- Agent Loop
- Tool Calling
- Memory
- Planning
- MCP / API Integration
- Evaluation

#### 编排说明与跨场景验证

- **[修改] Agent 编排算法说明：wzy 主责，王语嫣提供工具实现细节**。说明意图与实体解析、澄清、任务拆解、依赖关系、工具选择、状态流转、结果核验及失败处理；明确 LLM、规则和业务服务各自承担的工作。

- **跨场景规划：wzy 主责，王语嫣、袁爱岑、谢涵微、杨婧柔提供各自模块**。将分析、模拟、订阅调整、预算和明确授权的转账连接成一条可验证主线；对部分成功、失败和未知结果分别处理。

- **[修改] Agent 与端到端测试：wzy 主责编排修复，杨婧柔主责案例及验收**。覆盖意图、澄清、工具选择、步骤依赖、用户修改、错误恢复以及联动流程；检查实际业务状态和副作用。

### 2.4 Module 3 —— Financial Data Engine

负责所有金融数据：

```text
Raw Data
   ↓
Cleaning
   ↓
Normalization
   ↓
Categorization
   ↓
Feature Engineering
   ↓
Financial Profile
```

核心数据：

```text
Account
Transaction
Income
Expense
Asset
Liability
Portfolio
User Profile
```

#### 负责人

**袁爱岑主责金融数据分析、清洗、分类与模型实现；王语嫣负责数据库、后端与数据接口。**

#### 数据、数字孪生与计算口径

- **账单分析与数字孪生：袁爱岑主责，王语嫣提供数据接口，谢涵微展示，杨婧柔验收**。清洗、分类、对账、生成带来源和版本的财务快照；交付计算代码、算例和技术文档内容。

- **[修改] 数据与金融算法说明：袁爱岑主责，wzy 审核口径**。说明数据字段、清洗去重、分类、退款与内部转账处理、现金流和现金结余率、数字孪生更新、事件日期模拟、最低余额与方案比较；附手工可核对的算例。

- **[新增] 算法假设与局限：袁爱岑主责**。记录样本范围、缺失数据、预计收入依据、订阅生效时间、预算节约假设、币种与精度；区分历史事实、用户输入和预测。未实现的随机模拟或投资指标不作为已交付能力描述。

- **[修改] 数据与计算测试：袁爱岑主责，杨婧柔纳入统一报告**。覆盖零／负收入、重复交易、退款、本人转账、信用卡重复统计、缺失类别、收入延迟、日期顺序、订阅生效和预算预留；用参考结果核对金额。

以上现金流与现金结余率口径需与本章公式、代码及演示保持一致；历史事实、用户输入和预测分别标明。

### 2.5 Module 4 —— Quant / Financial Intelligence Engine

这是金融数学背景可以重点打造的部分。

#### Cash Flow

$$
CF_t=Income_t-Expense_t
$$

#### Saving Rate

$$
SR_t=\frac{Income_t-Expense_t}{Income_t}
$$

#### Liquidity

$$
LR=\frac{Liquid\ Assets}{Short\text{-}Term\ Obligations}
$$

#### Debt Burden

$$
DBR=\frac{Debt\ Payment}{Income}
$$

#### Portfolio Risk

$$
\sigma_p^2=w^T\Sigma w
$$

还可以加入：

- Expected Return
- Volatility
- Sharpe Ratio
- VaR
- Maximum Drawdown
- Scenario Analysis
- Cash Flow Forecast

推荐架构：

```text
Agent
 ↓
“Calculate portfolio risk”
 ↓
Quant Engine
 ↓
Python / Mathematical Model
 ↓
Structured Result
 ↓
Agent Explanation
```

而不是让 LLM 自己计算。

#### 负责人

**袁爱岑（Financial Data & Quant Engineer），wzy 审核金融逻辑、模型口径与任务接口。**

#### 确定性情景模拟与环境生成 Agent

- **确定性情景模拟：袁爱岑主责，wzy 审核任务接口**。比较基准、旅行预算、订阅调整和收入变化方案，输出期末余额、期间最低余额、现金结余与假设；与 PPT 和 Demo 的数值保持一致。

- **环境生成 Agent 搭建：袁爱岑负责**。与其金融数据分析、量化和模型实现职责衔接，交付内容按实际完成情况说明。
- 环境生成 Agent 的搭建任务与随机模拟是否已经实现分别记录；未实现的随机模拟或投资指标不作为已交付能力描述。

### 2.6 Module 5 —— RAG / Financial Knowledge Base

负责金融知识：

```text
Banking Documents
Product Documents
Policy Documents
FAQ
Risk Disclosure
Business Rules
Competition-provided Data
```

架构：

```text
Documents
    ↓
Chunking
    ↓
Embedding
    ↓
Vector Database
    ↓
Retriever
    ↓
Reranker
    ↓
LLM
```

回答最好保留：

```text
Source
Document
Section
Timestamp
```

#### 负责人

**杨婧柔（NLP / RAG Engineer），同时负责知识库、测试与 Feedback；wzy 负责与编排器集成及调用边界审核。**

#### 知识治理、文档说明与对抗测试

- **RAG 与资料治理：杨婧柔主责，wzy 负责与编排器集成**。保证资料有来源与版本，回答有可核验引用，外部内容不能授予执行权限。

- **[修改] RAG 与知识检索说明：杨婧柔主责，wzy 审核调用边界**。说明资料来源、版本、有效期、分块、检索、引用核验与无依据时的处理；外部资料只能提供信息，不能授予权限或修改策略。

- **[修改] RAG 与安全对抗测试：杨婧柔主责，wzy、王语嫣修复控制问题**。覆盖资料过期、错误引用、无依据回答、直接／间接提示注入、越权和敏感信息泄露；验证工具调用与账户状态，不仅查看模型回答。

### 2.7 Module 6 —— Tool Calling Layer

建立统一 Tool Registry：

```text
TOOLS
│
├── get_account_balance()
├── get_transactions()
├── analyze_cashflow()
├── calculate_financial_health()
├── calculate_risk()
├── search_products()
├── compare_products()
├── retrieve_policy()
├── calculate_loan()
├── calculate_portfolio()
├── create_budget()
├── create_alert()
└── execute_transaction()
```

Agent 根据任务选择工具。

例如：

```text
User
 ↓
“分析过去三个月消费”
 ↓
get_transactions()
 ↓
analyze_cashflow()
 ↓
generate_report()
```

#### 负责人

**王语嫣主责 Tools、API 与业务适配器实现，wzy 主责工具契约、编排及关键接口审查；双方与 Module 2 共同维护 Tool Registry 的注册、Schema 与调度。**

#### 业务执行与接口证据

- **智能转账：王语嫣主责，wzy 编排，谢涵微确认交互，杨婧柔验收**。实现收款人澄清、预览、确认、认证条件、重新校验、幂等提交和回执查询。

- **订阅／代扣管理：王语嫣主责业务操作，袁爱岑主责重复扣费识别，谢涵微展示（保证UI呈现正常），杨婧柔核对协议规则**。候选识别与确认取消分开；仅凭流水不宣称服务未使用，未来节约与当前余额分开。

- **[新增] 接口与执行证据：王语嫣主责并整合入技术文档，杨婧柔协助核对材料**。提供输入输出、错误码、操作状态、确认记录和回执示例；区分草案、待确认、已提交、成功、失败、部分成功和未知状态。

- **[修改] 后端与业务测试：王语嫣主责，杨婧柔纳入统一报告**。覆盖资源隔离、参数错误、确认缺失／过期／不匹配、余额不足、幂等、超时、未知状态和回执核验。

### 2.8 Module 7 —— Risk & Compliance Guard

```text
                Agent Output
                     ↓
             ┌───────────────┐
             │ Safety Guard   │
             ├───────────────┤
             │ Permission     │
             │ Compliance     │
             │ Risk           │
             │ Data Privacy   │
             │ Hallucination  │
             └───────┬───────┘
                     ↓
             ┌───────┴───────┐
             ▼               ▼
            PASS           BLOCK
             │               │
             ▼               ▼
         Execute        Human Review
```

#### Human-in-the-loop

```text
LOW RISK
→ Agent automatically handles

MEDIUM RISK
→ Agent generates recommendation
→ User confirms

HIGH RISK
→ Human review / explicit approval
```

#### 负责人

**wzy 主责 Guardian 策略、安全设计与调用路径，王语嫣负责服务端强制执行，杨婧柔负责对抗验证，谢涵微负责安全自评材料。** 通用 6 人方案中由成员 F（RAG / Security / QA）担任 Security / Compliance Engineer；通用 5 人方案中可由 Backend 成员兼任，均不替代本团队实名分工。

#### 安全设计与权限分级

风险等级、操作权限与确认要求分别判断；工具契约要求用户确认的操作，即使标为低风险，也须按契约完成确认。

- **[修改] 安全设计：wzy 主责，王语嫣提供服务端实现，杨婧柔提供攻击测试证据**。说明认证、资源授权、最小权限、工具允许列表、参数校验、确认绑定、执行前复核、幂等、脱敏、审计及提示注入防御；交付设计与实际实现的对应关系。

- **Guardian 策略与安全网关：wzy 主责规则和路径，王语嫣主责强制执行，杨婧柔主责对抗验证**。安全设计、自评和实际调用日志使用同一套策略版本。

- **[修改] 权限分级规则定义：wzy 主责，王语嫣实现，谢涵微写入自评，杨婧柔提供测试证据**。分别列明已授权查询、分析模拟、预算／提醒写入、订阅／代扣变更、资金交易的最低控制要求；明确读取权限不能自动升级为执行权限。

### 2.9 Module 8 —— Security

#### Authentication

```text
User
 ↓
Login
 ↓
Authentication
 ↓
Session
```

#### Authorization

```text
Read Account
      ↓
Analyze Data
      ↓
Generate Recommendation
      ↓
Create Plan
      ↓
Execute Transaction
```

#### Prompt Injection Protection

```text
Input
 ↓
Security Filter
 ↓
Intent
 ↓
Permission Check
 ↓
Tool
```

#### 负责人

**王语嫣负责认证、资源授权、权限执行与后端安全实现；wzy 审核策略及执行路径；杨婧柔提供攻击测试证据；谢涵微整合安全自评。** 通用 6 人方案中由成员 D / F 协作承担 Backend Engineer / Security Engineer 职责。

### 2.10 Module 9 —— Audit & Monitoring

所有关键 Agent Action 应记录：

```json
{
  "user_id": "...",
  "intent": "...",
  "tool": "...",
  "input": "...",
  "output": "...",
  "risk_check": "...",
  "approval": "...",
  "timestamp": "..."
}
```

完整 Audit Trail：

```text
User Request
      ↓
Agent Decision
      ↓
Tool Call
      ↓
Financial Calculation
      ↓
Risk Check
      ↓
User Approval
      ↓
Execution
```

#### 负责人

**王语嫣负责日志落库与链路追踪；wzy 定义事件与状态；袁爱岑维护财务快照更新；杨婧柔负责审计规则验证与回归校验。**

#### 审计与状态回写

- **审计与状态回写：王语嫣主责基础实现，wzy 定义事件与状态，袁爱岑维护快照更新，杨婧柔验证**。记录请求、校验、确认、提交和核验事件；未知结果不提前改变财务事实。

---

## 第三部分：团队组建、协作流程与项目落地

本团队的实名职责及附加材料负责人以第四部分为准，这个第3节就看看实际产品落地的一些example和设计架构就行


### 3.2 如果团队只有 5 人（标准技术分工，备选）

```text
A = PM + Agent Architect
B = Agent + RAG
C = Quant + Data
D = Backend + Security
E = Frontend + QA
```

> 说明：本节适用于成员技术栈相对均衡的标准 5 人团队。若团队实际构成为「1 名大二 + 4 名大一」，请直接采用第四部分的最终推荐分工方案。


团队结构：

```text
                PM / Architect
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
      Agent         Quant         Backend
        │             │             │
        ▼             ▼             ▼
      RAG          Financial      Security
        │           Model            │
        └─────────────┬──────────────┘
                      ▼
                  Frontend
                      │
                      ▼
                  QA / Eval
```

### 3.4 团队协作 Workflow：Contract-First Development

不要采用「大家各写各的，最后再合起来」。

建议采用 **Contract-First Development**。

#### Phase 1 —— Product Contract

首先定义：

```text
User
 ↓
Use Case
 ↓
Input
 ↓
Agent
 ↓
Tools
 ↓
Output
 ↓
Risk
```

例如：

```text
Use Case:
Personal Cash Flow Analysis

Input:
Transaction Data

Agent:
Financial Analysis Agent

Tools:
get_transactions()
analyze_cashflow()

Output:
Cash Flow Report

Risk:
Low

Human Approval:
No
```

#### Phase 2 —— API Contract

每一个模块先定义接口。

例如：

```python
analyze_cashflow(
    transactions,
    period
)
```

返回：

```json
{
  "income": 15000,
  "expense": 12000,
  "cashflow": 3000,
  "saving_rate": 0.20
}
```

Agent 不需要知道内部怎么计算：

```text
Agent Team
       │
       │ API
       ▼
Quant Team
```

双方可以并行开发。

#### Phase 3 —— Agent Contract

规定 Agent 能调用哪些工具：

```text
Tool
├── Name
├── Description
├── Input Schema
├── Output Schema
├── Permission
├── Risk Level
└── Human Approval
```

例如：

```text
create_budget()

Permission:
User

Risk:
Low

Approval:
Required before activation
```

#### Phase 4 —— Integration

最终：

```text
Frontend
   ↓
Backend
   ↓
Agent
   ↓
Tool Registry
   ↓
Financial Engine
   ↓
Risk Engine
   ↓
Database
```

进行 End-to-End Test。

### 附加任务工作SOP（详细版）

#### 交付契约一：技术文档，必交

技术文档由王语嫣主责定稿。架构图、编排算法、数据与金融算法、RAG、安全设计、接口证据分别按第二部分对应模块的责任要求提供，统一纳入文档。

- **技术文档整合与定稿：王语嫣主责，wzy 技术审核，杨婧柔协调材料与提供评测内容**。汇总架构图、算法说明、安全设计和必要的接口、数据、评测说明，形成一份完整技术文档；建议内部文件名为 `技术文档.md`，最终格式按官网要求转换。

- **技术文档一致性检查：王语嫣主责，wzy、袁爱岑、谢涵微、杨婧柔核对各自内容**。确保文档、架构图、PPT、代码和 Demo 使用相同工具名、计算口径、参数与状态；王语嫣管理最终技术文档版本，杨婧柔同步提交材料版本记录。

#### 交付契约二：答辩 PPT，必交，汇报不超过 10 分钟

- **PPT 制作与版本管理：杨婧柔主责，谢涵微提供界面与可视化素材，全员核对各自内容**。汇总用户问题、三场景覆盖、创新机制、架构、算法、安全、结果和团队贡献；建议内部文件名为 `答辩PPT.pptx`，按平台要求准备最终格式。

- **架构、Agent 与 Guardian 页面：wzy 主责内容，杨婧柔负责排版**。提供准确的架构图、流程和控制证据，说明三个创新标签与实现对应关系。

- **数据、模型与模拟页面：袁爱岑主责内容，杨婧柔负责排版**。提供一致的演示金额、图表、公式口径和假设；复杂细节放入备份页，避免主报告超时。

- **代码、部署与执行页面：王语嫣主责内容，杨婧柔负责排版**。提供运行环境、工具链、实际回执与关键实现；演示能力必须与提交仓库一致。

- **测试、安全与已知风险页面：杨婧柔主责内容与排版，谢涵微提供安全自评，wzy 审核**。提供可追踪的测试结果、控制成功与失败案例、尚未解决的风险；不把有限测试通过表述为全面安全保证。

- **10 分钟汇报控制：杨婧柔主责，全员参加演练**。内部建议控制在约 9 分钟，留出操作切换余量；至少完成两次计时演练，并记录实际时长。图片没有规定固定页数，页数按内容和演练调整。

- **答辩讲述安排：wzy 主讲，谢涵微负责演示操作，王语嫣、袁爱岑、谢涵微、杨婧柔负责对应模块问答**。wzy 负责业务目标、架构、创新和整体结果；王语嫣回答接口与执行，袁爱岑回答计算与模拟，谢涵微回答前端交互与安全自评，杨婧柔回答资料、RAG、测试和 Feedback。具体上台人数与形式由杨婧柔核对官方规则。

- **PPT 最终导出与检查：杨婧柔主责并复核提交项，谢涵微协助检查展示效果**。检查文字、字体、图表、链接与页面顺序，确认汇报不超过 10 分钟，保存最终可打开版本。

#### 交付契约三：源代码，必交，包含 README、仓库、部署说明及测试用例

- **源代码仓库交付：王语嫣主责，全员提交各自模块**。整理前端、后端、金融计算、知识检索、测试、样例数据和必要配置；移除凭证及不应公开的数据，建立对应提交包的版本标识。

- **README：王语嫣主责，wzy 提供架构摘要，袁爱岑、谢涵微、杨婧柔提供模块说明**。包含项目简介、已实现能力、目录结构、环境要求、安装启动、演示入口、测试运行、已知限制和成员贡献；与实际仓库命令和路径一致。

- **部署说明：王语嫣主责，谢涵微配合前端，袁爱岑、杨婧柔配合数据与知识初始化**。说明依赖版本、配置项、环境变量、数据库初始化、样例数据加载、启动顺序、模型服务设置和常见问题；配置示例使用占位符，不提供真实密钥。

- **可复现运行核验：王语嫣主责，杨婧柔独立按说明验证**。在独立或干净环境中按文档启动，验证前端、后端、数据、知识检索与三个核心场景；运行失败由对应模块负责人修复，王语嫣更新说明。

- **测试用例整体交付：杨婧柔主责**。维护测试目录、案例编号、期望结果、运行方式与报告，确保测试代码随源代码提交；各模块负责人实现本模块的测试和修复。

- **仓库访问与提交版本核对：王语嫣主责，杨婧柔按平台规则复核**。确认评审方可按官方要求访问仓库，链接有效、指定版本存在、代码包完整；图片未明确要求公开仓库，不擅自将其设为公开。

后端与业务、数据与计算、前端与确认流程、Agent 与端到端、RAG 与安全对抗测试的覆盖范围，分别按第二部分对应模块的验收要求执行，由杨婧柔纳入统一测试报告。

#### 交付契约四：安全自评，必交，包含权限分级说明与已知风险清单

- **安全自评整合与定稿：谢涵微主责，wzy 技术审核，王语嫣、袁爱岑提供实现与限制，杨婧柔提供测试证据及风险记录**。建议内部文件名为 `安全自评.md`。该材料说明实际权限控制、测试证据与已知风险；与技术文档中的安全设计相互引用，避免两份材料出现不同规则。

- **权限分级说明成文：谢涵微主责，杨婧柔提供对应测试编号与证据，wzy 确认准确性**。逐项写出操作类型、所需身份／资源权限、确认要求、认证条件、允许／阻止结果、对应接口与测试编号。

- **权限与确认实现证据：王语嫣主责，谢涵微汇总入安全自评，杨婧柔协助核对证据**。提供资源校验、确认版本绑定、执行前复核和幂等的可追踪结果；wzy 检查是否存在绕过统一工具网关的路径。

- **已知风险清单：杨婧柔主责维护风险记录，谢涵微汇总入安全自评，全员报告本模块风险**。至少记录模型误解、错误参数、错误分类、过期／缺失数据、情景假设偏差、提示注入、越权、重复操作、超时未知、日志泄露及外部接口限制。

- **已知风险记录格式：杨婧柔主责维护记录，谢涵微用于安全自评**。每项风险包含编号、触发条件、影响、已有措施、测试证据、残余风险、解决状态和负责人；已缓解、待修复及暂不覆盖分别标明。

- **Agent 与策略残余风险：wzy 主责处置**。负责意图误解、任务依赖错误、Guardian 规则缺口、外部指令影响和执行路径绕过；杨婧柔更新风险记录。

- **接口、权限与执行残余风险：王语嫣主责处置**。负责越权访问、确认失效、重复提交、余额变动、未知结果、凭证和部署配置；杨婧柔更新风险记录。

- **数据与模型残余风险：袁爱岑主责处置**。负责分类误差、重复统计、收入与支出缺失、币种精度、模拟假设和目标资金重复计入；杨婧柔更新风险记录。

- **交互残余风险：谢涵微主责处置**。负责确认信息不完整、状态误导、金额单位不一致、过期结果展示及参数改变未提示；杨婧柔更新风险记录。

- **知识与评测残余风险：杨婧柔主责处置**。负责来源不明、规则过期、引用不支持结论、测试覆盖不足和材料夸大能力；涉及代码控制时交由 wzy 或王语嫣修复。

- **自评与测试一致性核对：谢涵微主责，杨婧柔核对测试证据，wzy 最终审核**。每项“已实现”“已验证”声明对应代码与测试；未完成措施按实际状态披露，不能以计划代替实现。

权限分级规则由 wzy 定义、王语嫣实现、谢涵微写入自评，具体操作范围与证据要求见 2.8；杨婧柔提供测试证据并维护风险记录。

#### 交付契约五：演示视频，可选，不超过 5 分钟

- **是否制作视频与资源安排：谢涵微主责评估，wzy 确认主线稳定，杨婧柔确认必交材料完成情况**。视频为可选项，优先保证四项必交材料完整；不能将视频当成必交，也不能用视频替代技术文档、PPT、源代码或安全自评。

- **视频脚本、录制与剪辑：谢涵微主责，杨婧柔核对字幕和材料一致性**。展示需求输入、财务快照、方案比较、订阅处理、转账确认、实际回执和一个控制案例；建议时长约 4 分 30 秒，最终不得超过 5 分钟。

- **录制环境与演示数据：王语嫣主责准备环境，袁爱岑主责数据和计算结果，wzy 核对主流程**。确保录制可重复，金额和回执与当前提交版本一致；明确模拟或沙箱环境。

- **视频最终检查：谢涵微主责，杨婧柔复核时长、格式和上传状态**。去除真实凭证及敏感信息，检查画面、声音、字幕与播放；有剪辑时不将剪辑效果冒充实时执行能力。

### 3.5 最重要的 Agent Loop

```text
                    ┌──────────────┐
                    │     USER     │
                    └──────┬───────┘
                           ↓
                  ┌────────────────┐
                  │ Intent Parsing │
                  └───────┬────────┘
                          ↓
                  ┌────────────────┐
                  │    Planner     │
                  └───────┬────────┘
                          ↓
              ┌───────────┴───────────┐
              ↓                       ↓
       Financial Data             Knowledge
              ↓                       ↓
              └───────────┬───────────┘
                          ↓
                    Tool Calling
                          ↓
                  Financial Engine
                          ↓
                  Risk / Compliance
                          ↓
                    Verification
                          ↓
                  User Confirmation
                          ↓
                      Execute
                          ↓
                    Audit Log
                          ↓
                     Monitor
                          │
                          └─────────────┐
                                        │
                                        ▼
                                   Next Action
```

### 3.6 推荐比赛 Demo：End-to-End Banking Journey

不要展示十几个没有关联的功能，建议设计一个完整的 **End-to-End Banking Journey**。

#### Scenario

用户：

> **「我最近发现自己每个月都存不下来钱，帮我分析一下，并制定一个下个月的预算。」**

[此处建议补充：Demo 使用的演示数据来源（比赛官方提供的数据集，或自行构造的模拟交易数据）]

#### Step 1 —— Agent 理解需求

```text
Intent:
Financial Health Analysis

Subtasks:
1. Analyze income
2. Analyze expenses
3. Identify abnormal spending
4. Calculate saving rate
5. Generate budget
```

#### Step 2 —— 获取金融数据

```text
Transaction Database
        ↓
Last 6 Months
        ↓
Income / Expense
```

#### Step 3 —— Quant Engine

例如：

```text
Income
¥15,000

Expense
¥13,500

Cash Flow
¥1,500

Saving Rate
10%
```

#### Step 4 —— 找出原因

```text
Food
+12%

Shopping
+27%

Transport
+5%

Fixed Expense
Stable
```

Agent 可以基于上述数据解释：

> 主要变化来自可选消费，而非固定支出。

#### Step 5 —— 生成预算

```text
Monthly Budget

Housing       ¥5,000
Food          ¥2,000
Transport     ¥1,000
Shopping      ¥1,000
Other         ¥1,000
Savings       ¥5,000
```

#### Step 6 —— Risk Check

```text
Budget
 ↓
Risk Engine
 ↓
PASS
```

#### Step 7 —— 用户确认

```text
┌─────────────────────────────┐
│ AI建议建立新的月度预算      │
│                             │
│ 每月储蓄目标：¥5,000        │
│                             │
│ [确认]          [修改]      │
└─────────────────────────────┘
```

#### Step 8 —— Agent 执行

```text
create_budget()
      ↓
Database
      ↓
Budget Created
```

#### Step 9 —— 持续监控

```text
Actual Spending
       ↓
Budget Comparison
       ↓
Overspending Detection
       ↓
AI Notification
```

形成：

$$
Understand
\rightarrow
Analyze
\rightarrow
Plan
\rightarrow
Verify
\rightarrow
Execute
\rightarrow
Monitor
$$

#### 跨场景演示故事

- **[新增] 业务故事与场景呈现：杨婧柔主责，谢涵微配合演示呈现**。围绕旅行财务规划、账单分析、订阅管理和智能转账组织一个连贯案例，清楚展示输入、方案、确认与实际结果。

以旅行财务规划为连贯故事，将账单分析、订阅管理和智能转账三个核心场景与数字孪生、方案比较、预算及确认执行相衔接。主线必须能展示实际业务状态和回执，并区分部分成功、失败和未知结果。

### 3.7 项目最终定位

不建议定位成：

> **AI 银行客服**

建议定位为：

> **AI Financial Operating Agent**

核心价值：

```text
Banking
    +
Artificial Intelligence
    +
Quantitative Finance
    +
Agent
    +
Risk Control
```

完整能力链：

```text
          UNDERSTAND
               ↓
             ANALYZE
               ↓
              PLAN
               ↓
             VERIFY
               ↓
             EXECUTE
               ↓
             MONITOR
```

### 3.8 最终技术架构

```text
┌─────────────────────────────────────────────────────────┐
│                         USER                            │
└───────────────────────────┬─────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                     FRONTEND                            │
│ Chat │ Dashboard │ Charts │ Confirmation │ Alerts       │
└───────────────────────────┬─────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                  AI BANKING AGENT                       │
│                                                         │
│ Intent │ Memory │ Planner │ Reasoning │ Tool Selection  │
└─────────────┬───────────────┬───────────────┬───────────┘
              │               │               │
              ▼               ▼               ▼
       ┌────────────┐  ┌─────────────┐ ┌──────────────┐
       │ RAG        │  │ Quant Engine│ │ Tool Registry│
       │ Knowledge  │  │             │ │              │
       └────────────┘  └─────────────┘ └──────┬───────┘
                                              │
                         ┌────────────────────┼──────────────────┐
                         ↓                    ↓                  ↓
                   Banking API          Product API        Data API
                         │                    │                  │
                         └────────────────────┼──────────────────┘
                                              ↓
                                  ┌─────────────────────┐
                                  │ Risk & Compliance   │
                                  │                     │
                                  │ Permission          │
                                  │ Risk                │
                                  │ Security            │
                                  │ Compliance          │
                                  └──────────┬──────────┘
                                             ↓
                                  ┌─────────────────────┐
                                  │ Human Confirmation  │
                                  └──────────┬──────────┘
                                             ↓
                                  ┌─────────────────────┐
                                  │ Execution Layer     │
                                  └──────────┬──────────┘
                                             ↓
                                  ┌─────────────────────┐
                                  │ Audit / Monitoring  │
                                  └─────────────────────┘
```

### 3.9 最终团队分工图

下图表达模块协作关系。实际对应为：wzy 负责总体架构、Agent 与集成把关，王语嫣负责 Agent 代码、Tools 与后端，袁爱岑负责金融数据、量化、模型实现及环境生成 Agent，谢涵微负责前端，杨婧柔负责知识库、RAG、测试与 Feedback。

```text
                         PM / ARCHITECT
                               │
                 ┌─────────────┼─────────────┐
                 │             │             │
                 ▼             ▼             ▼
              AGENT          QUANT         BACKEND
             / LLM          / DATA        / API
                 │             │             │
                 │             │             │
                 ▼             ▼             ▼
               RAG       Financial Model   Database
                 │             │             │
                 └─────────────┼─────────────┘
                               │
                               ▼
                       RISK / SECURITY
                               │
                               ▼
                          FRONTEND
                               │
                               ▼
                           QA / EVAL
```

### 3.10 最终项目优先级

如果比赛时间有限，不建议平均分配开发资源。

#### P0 —— 必须完成

```text
├── AI Banking Agent
├── Tool Calling
├── Financial Data
├── Quant Analysis
├── RAG
├── Risk / Permission
└── End-to-End Demo
```

#### P1 —— 强烈建议

```text
├── Financial Forecast
├── Personalized Financial Planning
├── Explainable AI
├── Audit Log
└── Monitoring
```

#### P2 —— 有时间再做

```text
├── Multi-Agent
├── Voice Banking
├── Advanced Portfolio Optimization
├── Fraud Detection
└── Autonomous Long-Term Agent
```

#### 扩展功能与实际交付边界

- **扩展功能取舍：wzy 主责，杨婧柔维护已实现清单**。产品比较、随机模拟、卡片管理等仅在主线与必交材料完成后增加；未实现内容清楚标为规划，不计入实际交付。

原优先级用于技术范围安排；四项必交材料、报名与有效提交同步落实，不能由可选视频或扩展功能替代。审计、确认和权限控制按实际执行链路的安全要求落实。

### 3.11 核心项目原则

整个项目可以用一句话定义：

> **不要证明「我们的 LLM 很聪明」，而要证明「我们的 Agent 能够安全、可解释、可验证地完成一个金融业务闭环」。**

因此最终技术壁垒应该集中在：

$$
\boxed{
Agent
\rightarrow
Financial\ Data
\rightarrow
Quant\ Engine
\rightarrow
RAG
\rightarrow
Risk/Compliance
\rightarrow
Execution
\rightarrow
Monitoring
}
$$

这条链跑通后，项目才真正形成 **FinTech + AI Agent + Quantitative Finance** 的完整参赛体系。

---

## 第四部分：面向「1 个大二 + 4 个大一」团队的优化分工方案（最终推荐）

### 4.1 为什么需要重新设计分工

对于 **「1 个大二 + 4 个大一」的 5 人团队**，不建议继续沿用第三部分那种「Agent / Quant / Backend / Frontend / RAG」五等分。

因为那种分法默认每个人都已经具备比较完整的技术栈，容易出现一个问题：

> **5 个人都有模块，但实际上只有 1 个人真正理解整个系统。**

本团队更适合采用：

> **「1 个技术总负责人 + 2 个核心开发 + 2 个低门槛但可逐步升级的岗位」**

而且应该让大一成员的工作**具有明确的学习曲线**，而不是一开始就要求他们独立负责复杂的 Agent、金融数学或者后端架构。

> 说明：本部分保留「1 个大二 + 4 个大一」的组织与成长逻辑，实际人员及附加材料分工按《Agent 大赛分工》落实；第三部分 3.1–3.3 中的通用人数方案仅作参考。

#### 分工依据与责任规则

- **更新依据**：沿用此前“1 名大二成员 + 4 名大一成员”的团队结构，结合本次图片中的人工智能赛道初赛要求，更新研发、材料、报名与提交责任。

- **标记说明**：[新增] 表示本次明确补入的责任；[修改] 表示已有责任的范围、负责人或交付标准得到调整；[未分配] 表示实际人选尚未确定。未加标记的条目沿用此前分工。

- **成员代号**：T 为大二成员；A、B、C、D 为四名大一成员。对应关系为：T＝wzy（成员 1），A＝王语嫣（成员 2），B＝袁爱岑（成员 3），C＝谢涵微（成员 4），D＝杨婧柔（成员 5）。wzy 沿用分工文件中的原记法。

- **责任规则**：每项工作只设一个主负责人；协作人提供指定内容，审核人负责检查。主负责人负责收集、整合、版本同步和完成状态，避免多人同时对同一份材料各自定稿。

- **要求性质**：图片中的报名时间、材料必交／可选状态、时长与评审安排为本次提取的主办方要求；下文建议文件名、内部节点、复核流程与演练次数属于团队实施安排。

### 4.2 重新定义团队组织结构

建议采用如下结构：

总体架构与集成：wzy（成员 1，大二，Tech Lead / Agent Architect）

| 协作岗位 | 实际成员 | 主要协作关系 |
|---|---|---|
| Agent / Backend | 王语嫣（成员 2，大一） | 实现 Agent 代码、Tools、API 与 Database，接入总体编排 |
| Quant / Data | 袁爱岑（成员 3，大一） | 提供金融数据、量化计算、模型实现与环境生成 Agent |
| Frontend / UI | 谢涵微（成员 4，大一） | 展示金融结果、聊天、方案、确认与执行状态 |
| RAG / QA / Research | 杨婧柔（成员 5，大一） | 向各模块提供知识检索、研究、测试、Feedback 与评测支持 |

但这里有一个非常重要的调整：

其中 Documentation 包括资料贡献、内容核验与提交材料协调；技术文档由王语嫣主责定稿，安全自评由谢涵微主责定稿，答辩 PPT 由杨婧柔主责定稿。

这是一个非常适合代码基础较弱、但愿意学习的成员的位置。

### 4.3 wzy（成员 1，大二）—— Tech Lead / Agent Architect

#### 定位

这是整个项目的：

> **系统总负责人 + Agent 核心负责人**

不是说其他四个人都听他指挥，而是他负责保证：

> **每个人写出来的东西最后能够拼成一个 Agent。**

#### 主要负责

```text
                 TECH LEAD
                     │
       ┌─────────────┼─────────────┐
       ↓             ↓             ↓
    Agent        Financial       System
 Architecture      Logic        Integration
```

具体：

- 总体架构
- Agent Workflow
- LLM 调用
- Prompt Framework
- Tool Calling
- Agent State
- API Interface 定义
- 模块之间的数据格式
- 最终 Integration
- Demo 主流程
- 最终技术答辩

#### 当前职责与审核边界

- **[修改] wzy｜技术负责人、Agent 架构与安全设计负责人**：负责总体架构、Action Agent 编排、Guardian 策略、任务状态机、工具契约、关键接口审查、集成和技术答辩；补充架构图、Agent 算法说明与安全设计内容。wzy 不自动等同于队长，也不承担全部材料排版、代码、测试和报名事务。

#### 不建议他负责

不要让大二成员同时负责：

- 前端全部代码
- 后端全部代码
- Quant 全部代码
- PPT
- 商业计划书
- 比赛材料
- 所有 Debug

否则最后会变成：

> **一个人写项目，四个人帮忙。**

这是应该避免的。

### 4.4 王语嫣（成员 2，大一）—— Agent / Backend Engineer

这个岗位最适合**代码能力相对较强的大一成员**。

#### 初始定位

> **Agent Implementation Engineer**

但注意：

**不要让其一开始就独立设计 Agent。**

而是：

```text
大二（成员 1）
  ↓
设计 Agent Workflow
  ↓
王语嫣（成员 2，大一）
  ↓
实现具体 Tool / API
```

#### 第一阶段负责

例如：

```python
get_transactions()

get_account_balance()

calculate_budget()

get_user_profile()
```

这些相对独立的 Function。

#### 第二阶段

逐渐负责：

```text
Tool Registry
     ↓
Function Calling
     ↓
Agent → Tool
```

#### 第三阶段

再进一步学习：

- FastAPI
- REST API
- JSON Schema
- Database
- Function Calling
- Agent Framework

最终可以达到：

```text
User
 ↓
Agent
 ↓
Tool
 ↓
Backend
 ↓
Database
```

#### 当前职责与材料交付

- **[修改] 王语嫣｜工具、后端、代码交付与技术文档负责人**：负责账户查询、收款人解析、订阅管理、转账适配器、API、数据库、权限执行、确认核验、幂等和回执；补充源代码仓库整理、README、依赖清单、部署说明与可复现运行检查；主责技术文档的收集、整合、定稿及版本管理。

#### 为什么这样安排？

因为如果直接跟他说：

> 「你负责 Backend。」

他很可能不知道：

- API 是什么
- Endpoint 是什么
- Schema 是什么
- Database 怎么设计
- Agent 怎么调用 API

但如果给他：

> `get_transactions()`

这个明确任务，他就可以边做边学。

### 4.5 袁爱岑（成员 3，大一）—— Financial Data & Quant Engineer

这个岗位需要谨慎地进行工作。

因为大一成员可能：

- 数学基础还没完全建立
- 没学过金融
- 不理解投资组合
- 不理解风险指标

所以：

> **千万不要一开始让其独立设计金融模型。**

#### 正确的分工方式

由大二成员（成员 1）负责：

> **金融模型设计 / 指标定义**

袁爱岑（成员 3） 负责：

> **数据处理 + 模型实现 + 可视化**

例如成员 1 先定义：

$$
SavingRate=\frac{Income-Expense}{Income}
$$

然后成员 3 完成：

```python
def calculate_saving_rate(income, expense):
    return (income - expense) / income
```

#### 成长路线

**Level 1**：数据清洗

```text
CSV
 ↓
Pandas
 ↓
Clean Data
```

**Level 2**：交易分类

```text
Transaction
 ↓
Food
Shopping
Transport
Rent
Entertainment
```

**Level 3**：计算

- Cash Flow
- Saving Rate
- Expense Ratio
- Debt Ratio
- Liquidity Ratio

**Level 4**：再进一步

- Portfolio Return
- Volatility
- Sharpe Ratio
- VaR
- Drawdown

#### 当前职责与环境生成 Agent

- **[修改] 袁爱岑｜金融数据、数字孪生、算法说明与环境生成 Agent 搭建负责人**：负责清洗、分类、现金流指标、财务快照、确定性情景模拟及计算验证；补充公式、假设、输入输出、异常处理、算例和模型局限的正式说明；负责环境生成 Agent 搭建。

#### 这个岗位真正的定位

不要叫：

> Quant Researcher

而应该叫：

> **Financial Data & Quant Engineer**

这样更符合他的实际任务。

### 4.6 谢涵微（成员 4，大一）—— Frontend / Visualization

这个岗位实际上是**代码基础需求中等的岗位**。

前端可以快速获得反馈：

```text
写代码
 ↓
刷新网页
 ↓
马上看到结果
```

学习动力通常比较强。

#### 负责

**Dashboard**：

```text
Balance
Cash Flow
Expense
Financial Health
Risk
```

**Chat Interface**：

```text
User
 ↓
AI Banking Assistant
```

**Agent Status**：这一点特别建议加入。

例如：

```text
AI 正在分析你的交易……

✓ 获取账户数据
✓ 分析过去 6 个月消费
✓ 计算现金流
● 生成预算
○ 风险检查
```

这会让评委明显感受到：

> **这是 Agent，而不是 Chatbot。**

#### 技术路线

不需要一开始学 React + TypeScript + Next.js + Tailwind + 三个 UI Library。太容易爆炸。

建议：

```text
HTML / CSS / JS
        ↓
React
        ↓
简单 Dashboard
        ↓
API 调用
        ↓
Charts
```

如果时间非常紧，可以直接：

> React + 一个成熟组件库 + Chart Library

不要自己造 UI 组件。

#### 当前职责与附加材料

- **[修改] 谢涵微｜前端、安全自评负责人**：负责仪表盘、对话、方案比较、确认卡、任务进度和回执展示；主责整合、定稿安全自评，向答辩 PPT 提供前端与可视化素材，并在必交材料完成后制作可选视频、控制视频时长。

### 4.7 杨婧柔（成员 5，大一）—— RAG / Research / Evaluation

这个岗位非常关键。

而且它是四个大一成员中：

> **代码基础要求相对低的岗位。**

不要小看它。

#### 职责一：金融知识库

负责整理：

```text
金融知识
   ↓
Documents
   ↓
Chunking
   ↓
Embedding
   ↓
Vector DB
```

例如：

- 银行业务规则
- 产品说明
- 金融术语
- 风险提示
- 比赛提供的数据
- 官方资料

#### 职责二：RAG

学习：

- Embedding
- Vector Database
- Retrieval
- Reranking
- Prompt Grounding

最后形成：

```text
User Question
      ↓
Retriever
      ↓
Relevant Documents
      ↓
LLM
      ↓
Answer + Source
```

#### 职责三：Evaluation

这个其实非常重要。

可以建立：

```text
100 个测试问题
```

例如：

```text
Q1: 查询账户余额
Q2: 查询消费
Q3: 制定预算
Q4: 产品比较
Q5: 风险问题
Q6: Prompt Injection
Q7: 越权访问
...
```

然后测试：

| Test | Expected | Actual | Pass |
|---|---|---|---|
| Q1 | 正确余额 | 正确 | ✓ |
| Q2 | 正确消费 | 正确 | ✓ |
| Q3 | 正确预算 | 正确 | ✓ |
| Q4 | 有数据依据 | 正确 | ✓ |
| Q5 | 风险提示 | 缺失 | ✗ |

这样他就变成：

> **AI Evaluation Engineer**

而不是「负责文档的人」。

#### 当前职责与附加材料

- **[修改] 杨婧柔｜知识库、RAG、测试、Feedback、答辩 PPT 与提交材料协调负责人**：负责赛事要求登记、知识资料与 RAG、测试集、对抗测试、回归报告和来源核验；主责答辩 PPT 制作、定稿、汇报时长控制，以及报名信息准备、提交材料清单和版本记录。技术文档由王语嫣主责定稿，安全自评由谢涵微主责定稿，杨婧柔提供资料、测试证据并协调提交；代码与部署内容由王语嫣提供，可选视频由谢涵微提供，杨婧柔不重复撰写对应技术内容。


### 4.8 五个互补角色的总览

| 成员 | 代号 | 年级 | 角色 | 核心任务 | 附加材料或专项责任 | 难度 |
|---|---|---|---|---|---|---|---|
| wzy（成员 1） | T | 大二 | **Leader/Tech Lead / Agent Architect** | Agent、总体架构、综合集成、各部分把关 | 架构、编排与安全设计审核，技术答辩 | ★★★★★ |
| 王语嫣（成员 2） | A | 大一 | **Agent / Backend Engineer** | Agent 代码、Tools、API、Database、Backend | 技术文档、源代码、README、部署说明 | ★★★★ |
| 袁爱岑（成员 3） | B | 大一 | **Financial Data / Quant Engineer** | 金融数据分析、量化、模型实现、数字孪生与情景模拟 | 环境生成 Agent 搭建，算法说明与算例 | ★★★ |
| 谢涵微（成员 4） | C | 大一 | **Frontend / Visualization** | Dashboard、UI、聊天模块、可视化、确认与回执展示 | 安全自评、可选演示视频 | ★★★ |
| 杨婧柔（成员 5） | D | 大一 | **RAG / Research / Evaluation** | 知识库、RAG、测试、评测、Feedback | 答辩 PPT、材料协调、报名资料与提交清单 | ★★→★★★★ |

这个结构的一个巨大优点是：

> **大一成员不是被迫承担自己目前不会的东西，而是在项目中逐渐升级。**

### 4.9 「主负责人 + Shadow」制度：不要让每个人完全独立

例如：

```text
Agent
Owner: wzy（成员 1，大二）
Shadow: 王语嫣（成员 2，大一）

金融模型设计 / 指标口径审核
Owner: wzy（成员 1，大二）
Shadow: 袁爱岑（成员 3，大一）

金融数据分析 / 量化 / 模型实现 / 环境生成 Agent 搭建
Owner: 袁爱岑（成员 3，大一）
Reviewer: wzy（成员 1，大二）

Backend
Owner: 王语嫣（成员 2，大一）
Reviewer: wzy（成员 1，大二）

Frontend
Owner: 谢涵微（成员 4，大一）
Reviewer: wzy（成员 1，大二）

RAG
Owner: 杨婧柔（成员 5，大一）
Reviewer: wzy（成员 1，大二）
```

这样做有两个作用。

**第一**：大二不会成为唯一知识源。

**第二**：大一会逐渐接管项目。

### 4.10 商业分析必须进入每个人的任务

因为本团队参加的是：

> **FinTechathon**

不是纯软件工程比赛。

所以不能出现：

```text
程序员：
“我们做了一个 Agent。”

评委：
“解决什么问题？”

程序员：
“……它可以调用工具。”
```

### 4.11 「Business → Agent → Quant → Engineering」闭环

每一个功能开发之前都必须回答：

```text
Business Problem
       ↓
User Need
       ↓
Agent Task
       ↓
Financial Logic
       ↓
Tool
       ↓
Implementation
       ↓
Evaluation
```

例如：

#### Business Problem

> 用户不知道为什么自己的储蓄率下降。

↓

#### Agent Task

> 分析过去 6 个月现金流。

↓

#### Financial Logic

$$
SR_t=\frac{Income_t-Expense_t}{Income_t}
$$

↓

#### Tool

```text
analyze_cashflow()
```

↓

#### Implementation

Backend + Quant

↓

#### Evaluation

> 100 个测试账户是否能够正确识别？

### 4.12 避免「全员从零学习」的陷阱

最危险的工作方式是：

```text
王语嫣（成员 2）：
我要学 Python

袁爱岑（成员 3）：
我要学机器学习

谢涵微（成员 4）：
我要学 React

杨婧柔（成员 5）：
我要学 LangChain

wzy（成员 1）：
我要学全部
```

然后两周过去：

> **大家都会一点，但没有任何东西能跑。**

### 4.13 核心技术栈收敛

这种 5 人队伍，技术栈越少越好。

建议：

```text
LLM
│
├── Agent
│
├── Python
│
├── FastAPI
│
├── PostgreSQL / SQLite
│
├── RAG / Vector DB
│
└── React
```

Quant：

```text
Python
├── NumPy
├── Pandas
└── SciPy
```

Visualization：

```text
React
+
Chart Library
```

不要为了「看起来高级」加入：

```text
Multi-Agent
+
Knowledge Graph
+
Graph Database
+
Kubernetes
+
Microservices
+
Kafka
+
Redis
+
复杂云架构
```

对于这个团队规模，**这些东西大概率是在增加开发风险，而不是增加比赛价值。**

上述技术栈收敛建议用于避免额外增加复杂度，不取消已明确分配给袁爱岑的环境生成 Agent 搭建任务。

### 4.14 推荐开发顺序

[此处建议补充：比赛实际可用时间；若赛程少于 5 周，可将 Week 4（Risk / Security）与 Week 3 并行推进，并把 Week 5 提前完成]

#### Week 1：所有人先理解同一个项目

五个人共同完成：

```text
Business Problem
      ↓
Use Cases
      ↓
System Architecture
      ↓
Data Schema
      ↓
Agent Workflow
```

此时不要急着写 UI。

#### Week 2：做最小 Agent

只做：

```text
User
 ↓
LLM
 ↓
Tool
 ↓
Financial Calculation
 ↓
Answer
```

例如：

> 「分析我的消费。」

跑通：

```text
get_transactions()
        ↓
calculate_expense()
        ↓
LLM
        ↓
Answer
```

#### Week 3：加入 RAG + Dashboard

```text
Frontend
   ↓
Agent
   ↓
RAG
   ↓
Financial Engine
```

#### Week 4：Risk / Security

加入：

- Permission
- Prompt Injection
- Risk Check
- User Confirmation
- Audit Log

#### Week 5：End-to-End Demo

只保留 **1–2 个最完整的业务场景**。

例如：

**Demo A**：AI Personal Financial Management

```text
Analyze
 ↓
Diagnose
 ↓
Budget
 ↓
Confirm
 ↓
Monitor
```

**Demo B**：Financial Product Assistant

```text
User Requirement
 ↓
Risk Profile
 ↓
Product Retrieval
 ↓
Quantitative Comparison
 ↓
Compliance
 ↓
Explanation
```

#### 赛事时间依据与待核对事项

以下赛事时间与要求沿用更新分工清单对图片的提取记录；日期按此前讨论的 2026 年赛事理解，准确截止时刻和未载明的规则仍须核对。前述 Week 1—Week 5 表示开发阶段顺序，须依据实际可用时间压缩或并行，不替代赛事截止日期与内部节点。

- **图片中的时间安排**：报名为 8 月 31 日—11 月 1 日；作品提交于 11 月 2 日截止；11 月 3—8 日线上评审，评出前十名晋级决赛。日期按此前讨论的 2026 年赛事理解；图片未提供准确截止时刻。

- **[修改] 评审日程记录**：杨婧柔负责将“11 月 3—8 日线上评审”加入项目日历，并核对此前记录的“11 月 10 日入围公布”是否仍有效。评审期间与结果公布日期分别管理，不将图片中的评审结束日期直接当成公布日期。

#### 报名要求与官网信息

- **[新增] 报名信息收集与核对：杨婧柔主责，wzy、王语嫣、袁爱岑、谢涵微分别提供并确认本人信息**。依据官网实际字段收集团队与全部五名成员的信息，检查必填项、拼写、联系方式和成员一致性；交付一份已核对的报名信息清单。

- **[新增] 报名资料与队伍信息一致性：杨婧柔主责**。确保报名、技术文档、PPT、仓库说明和提交材料中的队伍名称、项目名称及成员信息一致；人员变更时同步更新。

- **[未分配][新增] 队长官网报名最终提交：正式队长负责，杨婧柔协助准备和核对**。队长须在 11 月 1 日报名期结束前完成官网要求的提交；具体执行人待队长确定后填入。

- **[新增] 报名状态留存：杨婧柔主责，正式队长提供提交结果**。保存官网报名状态、提交记录或确认信息，核查是否完整提交全部成员；不以“资料已填好”代替报名成功。

- **[新增] 截止时刻与平台细则核对：杨婧柔主责**。核对报名与作品提交的准确时间、时区、上传入口、文件格式、大小限制、仓库访问要求以及账号操作权限；图片未写明的内容记录为待确认，不自行假定为 23:59。

- **[新增] 主办方通知跟踪：杨婧柔主责**。核对官网及官方通知中的更新，向全员同步时间、材料或规则变化；需要修改研发范围时由 wzy 评估，材料负责人同步调整。

#### 作品提交与版本管理

- **[新增] 提交材料总清单：杨婧柔主责**。逐项登记技术文档、答辩 PPT、源代码及其 README／部署说明／测试用例、安全自评；可选视频单独登记“提交”或“不提交”，每项记录负责人、版本和检查状态。

- **[新增] 提交包汇总：杨婧柔主责，wzy、王语嫣、袁爱岑、谢涵微交付各自定稿**。核对项目名称、成员、日期、场景、金额、仓库版本与材料链接，按平台要求命名和打包。

- **[新增] 作品上传与状态核对：杨婧柔主责协调，使用团队确认的授权提交账号执行**。图片只明确报名由队长提交，未明确作品上传是否也限定队长；杨婧柔核对平台规则。若限定队长，则由正式队长执行，杨婧柔继续负责材料和状态复核。

- **[修改] 11 月 2 日截止前持续优化：各模块负责人修改，杨婧柔管理提交版本**。平台以最后一次有效提交为准；每次替换材料后核对有效状态、文件版本和关联仓库版本，保留上一有效提交记录。

- **[新增] 最后一次有效提交确认：杨婧柔主责，提交账号执行人共同复核**。不能以点击上传或本地文件更新作为完成；核查平台显示的提交状态、材料完整性和最终版本，保存确认记录。

- **[新增] 提交问题处理：杨婧柔主责记录与协调，王语嫣处理文件／仓库／部署问题，杨婧柔处理 PPT 与材料协调问题，谢涵微处理安全自评／视频问题，wzy 处理技术一致性问题，袁爱岑处理计算数据问题**。涉及平台故障由杨婧柔按官方渠道询问，不未经确认改变材料要求。

- **[新增] 提交后归档：杨婧柔主责，王语嫣归档代码版本**。保存最终材料、有效提交记录、仓库版本、测试报告和可复现数据，保证评审期使用的说明能对应已提交作品。

#### 内部节点与线上评审分工

- **[新增] 内部进度跟踪：杨婧柔主责，全员更新自己的完成状态**。建议 10 月 28 日完成必交材料首稿，10 月 31 日形成可提交版本；内部日期为团队建议，正式截止仍按主办方确认信息执行。

- **[新增] 报名检查节点：杨婧柔主责核对，正式队长负责完成报名**。建议在 11 月 1 日之前留出核验余量，确认五名成员全部登记完成。

- **[新增] 作品预检查节点：杨婧柔主责，王语嫣完成运行复核，杨婧柔完成 PPT 计时，谢涵微完成安全自评检查**。建议 11 月 1 日检查上传文件、仓库访问、部署、测试、PPT 时长和自评完整性；截止前再次确认最后一次有效提交。

- **[新增] 11 月 3—8 日线上评审期间的通知与答复协调：杨婧柔主责**。跟踪官网和官方通知，分派问题，记录反馈；不自行假定评审期允许更新作品，补交或修改按官方要求办理。

- **[新增] 评审技术问题：wzy 主责总体回答，王语嫣回答接口与部署，袁爱岑回答计算与模拟，谢涵微回答交互、演示与安全自评，杨婧柔回答资料、RAG、测试、Feedback 与 PPT**。由杨婧柔统一协调问题归属与回复进度，避免多份相互矛盾的答复。

- **[新增] 晋级信息与后续安排：杨婧柔主责跟踪并同步**。图片说明评出前十名晋级决赛；具体公布时间和决赛材料要求待官方通知确认，不由图片自行推定。

#### 最终核对与尚待确定的信息

- **[新增] 图片要求覆盖核对：杨婧柔主责，wzy 复核技术项**。检查报名、全员信息、截止时间、四项必交材料、PPT 10 分钟限制、可选视频 5 分钟限制、最后一次有效提交规则以及线上评审安排均有责任人和状态记录。

- **[修改] 工作边界核对：wzy 主责技术边界，杨婧柔主责材料边界**。wzy 提供并审核架构／编排／安全；王语嫣维护仓库／README／部署并定稿技术文档；袁爱岑提供数据／模型／算例并搭建环境生成 Agent；谢涵微定稿安全自评／可选视频；杨婧柔定稿答辩 PPT／测试报告和提交清单。协作人不另行发布同名最终版本。

- **[未分配] 正式队长实际人选**：团队需确定并填入；这是目前唯一尚不能落实到具体成员的必需角色，影响官网报名最终执行。

- **[新增] 成员代号对应姓名：杨婧柔负责登记与维护**。依据分工文件登记 T＝wzy、A＝王语嫣、B＝袁爱岑、C＝谢涵微、D＝杨婧柔；人员信息变更时同步更新报名与全部材料。

- **[新增] 待确认信息跟踪：杨婧柔主责**。准确截止时刻、平台格式与大小限制、仓库访问方式、提交账号权限及结果公布时间尚未从图片获得，但均已分配核对负责人，不作为无人负责的事项留空。

- **[新增] 最终完成标准：杨婧柔负责材料核对，wzy 负责技术一致性，王语嫣负责技术文档与代码可运行，袁爱岑负责计算准确及环境生成 Agent 搭建，谢涵微负责前端展示、安全自评与可选视频时长，杨婧柔同时负责 PPT 定稿与汇报时长**。四项必交材料完整、报名与提交有效、代码和说明一致、所有关键结论有依据；视频若提交，须符合可选项要求。

### 4.15 主线 + 支线 Demo 策略

#### 主线：个人金融 Agent

```text
用户
 ↓
金融数据
 ↓
现金流分析
 ↓
Financial Health
 ↓
预算
 ↓
风险检查
 ↓
执行
 ↓
持续监控
```

这是整个 Demo 的核心。

#### 支线：Financial Product Assistant

```text
用户需求
 ↓
Product Search
 ↓
Product Comparison
 ↓
Risk Analysis
 ↓
RAG
 ↓
Explain
```

这样既展示：

> **AI Banking**

又展示：

> **金融智能**

#### 主线优先与支线启动条件

个人金融 Agent 为核心；更新清单中的账单分析、订阅管理、智能转账围绕同一条旅程展开。Financial Product Assistant、随机模拟、卡片管理等扩展只在主线与必交材料完成后增加；未实现能力按规划标明。环境生成 Agent 搭建由袁爱岑负责，其交付状态单独记录。

### 4.16 最终团队结构图

| 层级与岗位 | 成员 | 研发职责 | 材料及协作职责 |
|---|---|---|---|
| TECH LEAD / AGENT ARCHITECT / FINANCIAL LOGIC | wzy | 总体架构、Agent、金融逻辑审核、系统集成与各部分把关 | 技术审核与技术答辩 |
| Agent / Backend | 王语嫣 | Agent 代码、Tools、API、Database | 技术文档、代码仓库、README 与部署 |
| Quant / Data | 袁爱岑 | Financial Data、Calculations、Risk Metrics、模型实现 | 环境生成 Agent 搭建、公式假设与算例 |
| Frontend / UI | 谢涵微 | Dashboard、Chat UI、Visualization | 安全自评与可选演示视频 |
| RAG / Research / Evaluation | 杨婧柔 | RAG、Research、Evaluation、Security Testing、Feedback、资料贡献与文档协调 | 答辩 PPT、测试报告、报名资料及提交协调 |

wzy 负责五人工作的总体集成与审核；王语嫣、袁爱岑、谢涵微分别交付后端、金融数据与前端模块，杨婧柔与所有模块协作完成知识检索、测试和评测。

### 4.17 核心结论

最关键的一点：**不是「五个人做五个模块」**。

而应该是：

> **一个人负责系统架构，四个人围绕系统成长。**

最终形成：

$$
\boxed{
\text{Tech Lead}
+
\text{Agent}
+
\text{Quant}
+
\text{Frontend}
+
\text{RAG/Evaluation}
}
$$

而且每个人都应该有：

> **Primary Responsibility + Secondary Responsibility**

这样比赛后期不会出现某个人请假/代码出问题，整个模块就瘫痪。
