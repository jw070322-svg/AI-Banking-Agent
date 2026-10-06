# 2026 FinTechathon —— AI Banking Agent 项目架构与团队分工方案

> **项目定位：参赛项目设计文档 / Project Architecture v1.1**
>
> 本方案基于 2026 FinTechathon 官方赛事海报整理，围绕 **AI Banking、金融业务场景、AI Agent、金融数据、风险控制与合规** 展开设计。
>
> **文档结构**：第一部分为项目分析与用例设计；第二部分为系统架构与模块分工；第三部分为团队组建、协作流程与项目落地；第四部分为面向「1 个大二 + 4 个大一」团队的优化分工方案（本团队实际分工以第四部分为最终推荐）。
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

**Frontend Engineer / UI Designer**

### 2.3 Module 2 —— Agent Orchestrator

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

**Agent / LLM Engineer**

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

**Backend Engineer + Data Engineer**

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

**Quant / Data Scientist**

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

**NLP / RAG Engineer**

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

**Agent / LLM Engineer**（与 Module 2 共同维护 Tool Registry 的注册、Schema 与调度）

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

**Security / Compliance Engineer**（6 人方案中由成员 F（RAG / Security / QA）担任；5 人方案中可由 Backend 成员兼任）

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

**Backend Engineer + Security Engineer**（6 人方案中由成员 D / F 协作负责）

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

**Backend Engineer（日志落库与链路追踪）+ QA / Evaluation Engineer（审计规则与回归校验）**

---

## 第三部分：团队组建、协作流程与项目落地

### 3.1 推荐的 6 人团队

| 成员 | 角色 | 核心职责 |
|---|---|---|
| A | Product Manager / Agent Architect | 产品设计、系统架构、Agent Workflow |
| B | Agent / LLM Engineer | LLM、Prompt、Agent、Tool Calling |
| C | Quant / Data Scientist | 金融模型、风险模型、预测 |
| D | Backend Engineer | API、数据库、Agent Backend |
| E | Frontend Engineer | UI、Dashboard、可视化 |
| F | RAG / Security / QA | RAG、知识库、安全、测试、评测 |

### 3.2 如果团队只有 5 人（标准技术分工，备选）

```text
A = PM + Agent Architect
B = Agent + RAG
C = Quant + Data
D = Backend + Security
E = Frontend + QA
```

> 说明：本节适用于成员技术栈相对均衡的标准 5 人团队。若团队实际构成为「1 名大二 + 4 名大一」，请直接采用第四部分的最终推荐分工方案。

### 3.3 如果团队有 7 人（扩展方案）

增加一个岗位：**AI Evaluation / Compliance Engineer**。

专门负责：

- Hallucination Evaluation
- Agent Evaluation
- Financial Accuracy
- Security Testing
- Compliance Rules
- Red Team
- Prompt Injection Testing

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

> 说明：本部分为最终推荐方案。若采用本部分，第三部分 3.1–3.3 中的通用人数方案仅作参考。

### 4.2 重新定义团队组织结构

建议采用如下结构：

```text
                         大二成员（成员 1）
                  ┌──────────────────┐
                  │ Tech Lead /      │
                  │ Agent Architect  │
                  └────────┬─────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
    成员 2（大一）     成员 3（大一）     成员 4（大一）
   Agent / Backend    Quant / Data      Frontend / UI
          │                │                │
          └────────────────┼────────────────┘
                           │
                           ▼
                       成员 5（大一）
                 RAG / QA / Research
```

但这里有一个非常重要的调整：

**成员 5（大一）不应该被当成「剩下来的杂活人员」。**

他实际负责：

> **Research + RAG + Evaluation + Documentation**

这是一个非常适合代码基础较弱、但愿意学习的成员的位置。

### 4.3 成员 1（大二）—— Tech Lead / Agent Architect

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

### 4.4 成员 2（大一）—— Agent / Backend Engineer

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
成员 2（大一）
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

### 4.5 成员 3（大一）—— Financial Data & Quant Engineer

这个岗位需要稍微谨慎。

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

成员 3 负责：

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

#### 这个岗位真正的定位

不要叫：

> Quant Researcher

而应该叫：

> **Financial Data & Quant Engineer**

这样更符合他的实际任务。

### 4.6 成员 4（大一）—— Frontend / Visualization

这个岗位实际上是**最适合代码基础一般的大一成员之一**。

因为前端可以快速获得反馈：

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

### 4.7 成员 5（大一）—— RAG / Research / Evaluation

这个岗位非常关键。

而且它是四个大一成员中：

> **最适合代码基础较弱成员的岗位。**

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

### 4.8 五个互补角色的总览

| 成员 | 年级 | 角色 | 核心任务 | 难度 |
|---|---|---|---|---|
| 成员 1 | 大二 | **Tech Lead / Agent Architect** | Agent、架构、Integration | ★★★★★ |
| 成员 2 | 大一 | **Agent / Backend Engineer** | Tools、API、Database | ★★★★ |
| 成员 3 | 大一 | **Financial Data / Quant Engineer** | 数据、金融计算、模型实现 | ★★★ |
| 成员 4 | 大一 | **Frontend / Visualization** | Dashboard、Chat、可视化 | ★★★ |
| 成员 5 | 大一 | **RAG / Research / Evaluation** | 知识库、RAG、测试、评测 | ★★→★★★★ |

这个结构的一个巨大优点是：

> **大一成员不是被迫承担自己目前不会的东西，而是在项目中逐渐升级。**

### 4.9 「主负责人 + Shadow」制度：不要让每个人完全独立

例如：

```text
Agent
Owner: 成员 1（大二）
Shadow: 成员 2（大一）

Quant
Owner: 成员 1（大二）
Shadow: 成员 3（大一）

Backend
Owner: 成员 2（大一）
Reviewer: 成员 1（大二）

Frontend
Owner: 成员 4（大一）
Reviewer: 成员 1（大二）

RAG
Owner: 成员 5（大一）
Reviewer: 成员 1（大二）
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
成员 2：
我要学 Python

成员 3：
我要学机器学习

成员 4：
我要学 React

成员 5：
我要学 LangChain

成员 1：
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

### 4.16 最终团队结构图

```text
                         ┌──────────────────────┐
                         │     成员 1（大二）    │
                         │                      │
                         │  TECH LEAD           │
                         │  AGENT ARCHITECT     │
                         │  FINANCIAL LOGIC     │
                         └──────────┬───────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
     ┌────────────────┐    ┌────────────────┐    ┌────────────────┐
     │ 成员 2（大一）  │    │ 成员 3（大一）  │    │ 成员 4（大一）  │
     │                │    │                │    │                │
     │ Agent/Backend  │    │ Quant/Data     │    │ Frontend/UI     │
     │                │    │                │    │                │
     │ Tools          │    │ Financial Data │    │ Dashboard       │
     │ API            │    │ Calculations   │    │ Chat UI         │
     │ Database       │    │ Risk Metrics   │    │ Visualization   │
     └────────────────┘    └────────────────┘    └────────────────┘
              │                     │                     │
              └─────────────────────┼─────────────────────┘
                                    │
                                    ▼
                         ┌────────────────────┐
                         │    成员 5（大一）  │
                         │                    │
                         │ RAG / Research     │
                         │ Evaluation         │
                         │ Security Testing   │
                         │ Documentation      │
                         └────────────────────┘
```

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
