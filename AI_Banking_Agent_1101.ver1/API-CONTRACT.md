# Third_Agent 统一接口（响应 1.0.0；策略 integrated-demo-1026.1）

> 1030 订正：本文件头部原写 `integrated-demo-1.1`，与代码不符。实际策略常量是
> `first_agent/service.py:32` 的 `POLICY_VERSION='integrated-demo-1026.1'`，
> 转账预览/断言/确认绑定与审计都用它。已按代码订正，旧策略的确认不能继续执行。
> 已实现但本文件此前未列的路由见文末「1030 路由与端点核对」。

## 设计依据

vv 使用整数分、浏览器内存状态；eva 模拟工具使用 Decimal 元，交付还缺少包依赖；推荐模块使用 CNY 元；YUKI 返回字符串来源且无稳定证据结构。直接混接会产生金额歧义、多份账本和不可追溯回答。因此统一 HTTP 边界、单一 SQLite 状态，以窄适配层接入原模块。所有身份由服务端的演示会话确定，忽略客户端客户身份。

## 数据与响应

- 金额：CNY 整数分，禁止 bool、字符串、浮点、负数。`amount_minor` 是转账字段；兼容 vv RPC 的 `amount`、`available`、`min` 和账单 `amount` 也都是整数分。账单支出允许负数；创建交易金额必须大于零。
- 期限：API 推荐采用天，vv 目标采用模拟月，1 月固定 30 天，最早赎回结算为锁定期加 1 天。推荐和执行使用相同期限及当前配置金额上限。
- 账户：首版统一转出账户 `ACC-4821`，只支持当前演示客户的精确名册收款人。不会把 eva 的 ¥128,450.32 与 vv 的 ¥38,640 相加；eva 仅在适配校验时读取当前唯一账本余额。
- 业务时钟：`state.day` 为模拟时间的毫秒时间戳。预览/断言过期使用真实 epoch 秒，预览 300 秒、断言 120 秒；绑定中的过期时间必须是整数，避免 Python / JS 序列化歧义。
- 响应外壳：`schema_version, request_id, status, data, error, trace, simulated`。`error` 为 null 或 `{code,message}`。`status` 包括 succeeded / needs_input / awaiting_confirmation / unknown / processing / failed / rejected / cancelled / invalidated。RAG 自身状态位于 `data.status`，不混入金融操作状态机。
- 幂等：POST（建立会话除外）必须提供 `Idempotency-Key`。同会话同 key 同规范化参数返回原响应；改参复用 key 报 `IDEMPOTENCY_CONFLICT`。即使换 key，重复确认已提交的同一 operation 也不会再次执行。
- 快照：`GET /api/snapshot` 是登录演示所有者的虚构界面数据；Agent 业务查询另检查 consent.read。快照不提供其他客户数据，不作为真实银行认证实现。

## HTTP 资源

| Method | Path | 关键参数 / 返回 | 权限与用途 |
|---|---|---|---|
| POST | /api/session | {}；设置 HttpOnly、SameSite=Strict cookie | 建立或复用本机演示会话 |
| GET | /api/health | ready, persistent, mode, analysis.available | 服务健康 |
| GET | /api/snapshot | state, catalog, total, capacity | 当前演示所有者快照 |
| GET | /api/accounts/overview | available_minor, positions_minor, total_minor, version | Agent 查询需 read |
| GET | /api/transactions?month=2026-10 | items, summary | 需 read；聚合结果为整数分 |
| GET | /api/subscriptions | 虚构订阅数组 | 需 read |
| GET | /api/products | 推荐结果及排除理由 | 教育演示目录 |
| POST | /api/recommendations | objective, top_k | 同一目录、金额、期限、风险适配 |
| POST | /api/knowledge | question, top_k, online_verify | BM25 原文证据，拒绝无证据生成；online_verify=true 时可选官网原文核验（见下节） |
| POST | /api/chat | message, month? | 规则路由、缺参澄清、查询依赖或转账预览 |
| POST | /api/transfers/preview | amount_minor, beneficiary_name, account_id? | trade，名册与余额/限额检查 |
| POST | /api/transfers/verify | operation_id, code | 模拟增强验证，返回 assertion_id |
| POST | /api/transfers/confirm | operation_id, confirmed:true, assertion_id?, outcome? | 重查绑定、权限、累计、过期、锁定；默认模拟成功 |
| POST | /api/transfers/reconcile | operation_id, result:pending/success/failed | read，仅核实原未知转账；演示结果选择器 |
| POST | /api/transfers/cancel | operation_id | 仅取消待确认操作 |
| GET | /api/operations/:id | 当前会话操作和回执 | 不能跨会话查单 |
| GET | /api/events | 最多 100 项脱敏 SQLite 审计 | 仅当前演示会话 |
| POST | /api/rpc | method, args:[] | vv 兼容适配，方法白名单与对应权限 |

## vv RPC 白名单

`authorize, configure, select, setProfile, analyze, summary, reviewSubscription, keep, budget, propose, cancel, verify, execute, reconcile, settle, settleCard, advance, pause, resume, unlock, liquid, projection, interpret, eligibility, total, capacity, monthlySaved`。

`propose(type,id?,amount?,options?)` 的 type 为 subscription / purchase / redeem / transfer / card_limit / card_lock / card_unlock / card_loss / card_apply。`execute(id,mode)` 的 mode 为 success / failed / unknown，属于模拟工具结果。申购与赎回必须先 `verify(id,"246810")`，并经过 120 秒断言及 300 秒预览有效性检查。`authorize({read,subscriptions,trade,cards?})` 前三个值必须均为 bool，cards 若提供也必须为 bool，缺省 false；授权有效期 24 小时，变更会使旧确认失效。`configure({total,need,emergency,months})` / `select(productId,amount)` / `budget(amount)` 只调整计划；不会执行金融变更。

同步 RPC 仅用于兼容 vv 现有渲染接口，页面数据通过服务端读取，业务引擎不在浏览器中执行。推荐模块是偏好排序，不产生收益预测或自动交易。当前 `trace` 外壳字段保留，计划见 chat.data.plan，详细审计见 events。

## 拒绝与执行语义

未知工具、缺权限、缺预览、过期或版本变化、未确认、无增强断言、余额/累计超限、账户越权均拒绝。转账当日累计含本次不超过 100000 分为黄色，超过为红色；该值为本项目原型约定。eva 单笔/日硬限额沿用配置，见 `first_agent/vendor/eva/policy_config.json`；这些均不是现实银行或现行法规声明。

未知结果未改已确认账本，同时阻止创建新金融写入。只有核实原回执后才扣账，不能重新提交。明确失败不改变余额。SQLite `BEGIN IMMEDIATE` 串行化事务；扣账、累计、操作状态、幂等返回、审计一起提交。跨进程测试验证同一操作只有一个提交成功。此保证限于共享同一个本地 SQLite 文件；不覆盖分布式银行事务。

日志先按字段脱敏，合法的 SHA-256 字段保持原样以供复算；自由文本、数字手机号和密码内容被脱敏。未经审核的知识文本仅供引用，不执行其中指令。所有接口只监听本机，HTTP 检查 Host/Origin。

## 卡管理与新转账扩展

POST /api/rpc 仍使用 {method,args:[]}。

| method / args | 含义 |
|---|---|
| propose / ["transfer","R-WANG",80000,{"cardId":"CARD-DEBIT"}] | 选择卡转账 800 元；trade 权限 |
| propose / ["card_limit","CARD-DEBIT",100000] | 调整卡每日限额 1000 元，不能低于今日已用 |
| propose / ["card_lock","CARD-DEBIT"] | 限制卡交易，不改变余额 |
| propose / ["card_unlock","CARD-DEBIT"] | 仅解锁 locked 卡，不能恢复 lost 卡 |
| propose / ["card_loss","CARD-DEBIT"] | 挂失后两条转账路径均受阻 |
| propose / ["card_apply"] | 模拟借记卡申请 |
| verify / [operation_id,"246810"] | 红色操作必需的模拟验证 |
| execute / [operation_id,"success"] | 明确确认后提交；failed/unknown 为模拟结果 |
| settleCard / [operation_id,"success"] | read 权限，推进次一模拟日查询审核；failed 不新增卡 |

card_* 需要 cards 权限及预览、验证、确认。审核 processing 不代表开卡成功；信用卡展示额度、调整额度、开卡均不增加可用资金。卡限额与 eva 单笔/日限额同时检查。

快照 state 增加 cards、contacts、externalOut。卡字段 id/name/last4/kind/status/limit/spent/spentDay/version，limit/spent 为分。可用+持仓+externalOut=初始资产。旧转账端点用默认 CARD-DEBIT，新 RPC 可选择卡。共享 transactions 日累计；旧 transfer_ops 只在公开快照投影进 operations，不重复保存操作。

服务端恢复 preserveVerification:true 不接受 HTTP 指定；验证仍需服务端绑定、策略、会话和时限校验。旧状态缺卡时补默认结构并使旧待确认失效。真实时钟校验期限，模拟日期用于卡审核。

## 独立场景生成（Third_Agent 增量）

`POST /api/scenarios/generate` 需要本机会话和 Idempotency-Key，无需金融写权限。全部 A–G 通过本包 `modules/环境生成agent/scenario_adapter.py` 生成并双层校验；不写会话账本。

| 请求 | 返回 data | 金额语义 |
|---|---|---|
| `{ "requirement": "普通银行用户" }` | 兼容 `schema_version:"scenario-1.0"`，顶层无 user | transactions.amount_minor **带符号**；id 为旧字段 |
| `{ "prompt": "配偶生日锁定1000元", "seed":42, "reference_date":"2026-10-23" }` | 完整 `schema_version:"1.0.0"`，A–G 分析契约 | amount_minor **绝对值**，amount 带符号，transaction_id、direction、transaction_type |
| `{ "requirement":"信用卡", "format":"contract", "scenario_type":"G" }` | 同完整契约 | 同上 |

`format` 为 legacy/contract；有 prompt 时默认 contract，否则默认 legacy。prompt 和 requirement 同时给且不一致时拒绝。可选 scenario_type 为 A–G，seed 为 0 到 2^32-1 整数，reference_date 为真实存在的 YYYY-MM-DD；严格拒绝布尔 seed。用户输入 1–2000 字符。不支持的需求返回 SCENARIO_UNSUPPORTED；旧 legacy 保留 SCENARIO_INVALID。其余参数错误 INVALID_ARGUMENT。

对客接口拒绝 include_evaluation 和未知参数；输出不含 expected_insights/evaluation_only_fields。返回恒 simulated=true、ledger_modified=false。生成数据含脱敏卡片、账单、家庭/日历及场景专项块，缺块不编造。卡账单独立于存款，booked 才参与余额。

同会话相同 Idempotency-Key 原请求重放由主服务 requests 表持久化，改参复用报冲突。上游另有独立单机 SQLite 生成缓存；两者均不提供分布式保证。legacy 只是完整契约的兼容输出，不喂给分析 loader，也不是兜底 toolkit 的 scenario-1.1。


## 接入分工

团队维护模拟 API 与可替换契约；真实银行由组委会本地部署接入。eva 主责卡后端/风控，vv 主责交互，集成负责状态和回执，Ethan 提供场景，YUKI 维护知识与评测。

结论：新增卡管理与场景沿用统一外壳及整数分契约；金融业务共享账本，独立场景不改变实时资金。


## 只读分析与数据整理（接口文档增量 2026-10-24）

响应 envelope 和执行策略仍为 1.0.0 / integrated-demo-1026.1；本节为向后兼容的新增 API。默认启动端口 8768（各启动器会覆盖：8798/8799/8802/8803/8805/8806/8807，当前演示入口是 `启动产品行情版.bat` → 8807）。

| Method | Path | 请求/返回 | 权限 |
|---|---|---|---|
| GET | /api/analysis/status | available、tools、error | 已建会话；不读客户数据 |
| GET | /api/analysis?tool=bills.summary&month=2026-10 | data.tool/source/result/simulated/ledger_modified | consent.read 且未过期 |
| POST | /api/analysis | `{ "tool":"data.organize", "args":{ "days":30 } }` | consent.read；必须 Idempotency-Key |
| GET | /api/health | 新增 data.analysis.available | 仅可用性，不返回账本 |

会话工具：bills.summary、bills.categories、anomalies.detect、subscriptions.burden、cashflow.project、liquidity.available、budget.advice、analysis.pipeline、data.organize。默认 analysis.pipeline；scenario.generate 不能走会话分析入口。

参数沿用工具规范：账单 month/year；现金流/流动性 days；预算 days/month；pipeline days/month；organize 只接受 days；days 为 1–366 整数。GET 的数字字符串在桥内转整数。无参数的工具拒绝额外参数。所有会话工具拒绝 scenario_file、include_evaluation、data、context 等客户端数据/路径/标准答案参数，身份和账本均从 cookie 对应会话读取。

成功 data 为 `{tool,source:"session_ledger",result,simulated:true,ledger_modified:false}`。未知工具 TOOL_NOT_REGISTERED，参数错误 INVALID_ARGUMENT，缺 read 为 SCOPE_DENIED，授权过期 SCOPE_EXPIRED，模块不可用 ANALYSIS_UNAVAILABLE；失败不改金融状态。读取仍记录审计/幂等日志，ledger_modified=false 专指业务账本。

`data.organize` 的 result 含 views.analysis/recommendation/cards/display 与 manifest；分析金额为整数分，只有 recommendation.profile.budget_cny 为 CNY 元。上游个别带符号 amount 仍以分计，不能仅根据字段后缀猜单位。manifest 显示缺失数据，display 始终是派生只读摘要。对客不开放评测开关，离线 organizer 的显式评测能力仍保留。

会话 cards 使用 card_id/card_type/masked_card_number/status/transaction_limit_minor/spent_today_minor/source。无信用卡账单和事件时分别列入 missing；不会从额度推算欠款。initial_balance_minor 为当前余额减已记账流水的重建期初，不冒称原银行记录的期初。申购/赎回标为 investment_purchase/investment_redemption，不作为消费/退款。

### 推荐金额与来源

`GET /api/products` 与 `POST /api/recommendations` 新增 budget_basis：configured_minor、engine_capacity_minor、analysis_headroom_minor（未授权/不可用为 null）、applied_minor、source、analysis_status。

- 有有效 read 且整理可用：消费 organizer 的 recommendation 视图。最终 `applied_minor=min(state.amount, engine.capacity, view.conditions.budget_minor)`。
- 上游视图按已验证规则：正分析上限与配置取 min；零上限保留配置并给应急金提示。因此 source 仍可为 engine_capacity，同时 analysis_headroom_minor=0。
- 缺 read 或模块不可用：沿用旧配置/引擎容量；source=engine_capacity，analysis_status=not_authorized/unavailable；不会自动授予 read。
- 正上限实际收紧时 source=analysis；可用时 analysis_status=available。预算视图是草稿，产品推荐与最终执行仍受原引擎规则约束。

实时资金与操作继续以 /api/snapshot 和原金融回执为准。新整理和生成数据不导入会话，不改变 consent/version/操作状态，不让客户账本进入 RAG。

<!-- macro-quant-research:start -->
## 宏观量化研究增量（2026-10-24）

新增独立离线模块 [建模说明](research/macro_quant/项目目标与思路.md)、[参数与字段](research/macro_quant/params.json)、[核心代码](research/macro_quant/quant_recommender.py)。采用共同期限情景、宏观条件概率和均值/CVaR评分；原偏好推荐、预算回退、业务账本及审批规则保持不变。

接口新增的是 [离线契约](research/macro_quant/INTERFACE.md)，没有新增HTTP路由。真实数据尚未接入，合成验证不代表市场有效性。本增量状态与证据分别见 [接续记录](research/macro_quant/context.json) 和 [验证报告](research/macro_quant/verification.json)；不并入此前整合测试计数。
<!-- macro-quant-research:end -->


# 最新前端整合补充（2026-10-25）

最新入口为 /，backend-client通过同源异步HTTP连接。POST /api/session 建立或复用HttpOnly cookie会话；/api/snapshot读取服务快照，/api/rpc负责统一结构化操作。原有analysis、knowledge、recommendations、scenarios接口保留。

新增 POST /api/developer/login，body {"code":"bnbu"}，返回短时token与has_backup。后续 /api/developer/reset body {"confirmation":"重置演示"}、/restore body {"confirmation":"恢复备份"}、/logout 要求 X-Developer-Token。令牌绑定会话、服务端存储哈希、15分钟有效。可用环境变量BANK_DEV_PASSWORD替换默认测试码，不把正式密码提交进代码。

reset仅重置当前模拟会话并保留最近一次备份；restore使待确认操作失效并要求重新核对。旧幂等响应清除，版本单调增加。内部审计保留重置事件。HTTP层advance/setProfile与失败/未知模拟注入需要开发者令牌，普通查询不能藉此绕过执行权限。

interpret对现金流分析与知识查询返回路由；前端再调用对应接口，不把命中关键词当作批准交易。实际读写规则和金额单位沿用原契约。


## 最新统一助手RPC

POST /api/rpc，参数 {"method":"assistant","args":["给小王转账"]}。同一会话保存clarification与chat_draft_id。客户端不能提交解析候选或批准结果。route为transfer-conversation时，conclusion用于客户提示，preview用于核对；clear_pending只指导移除旧展示，不代表撤销已完成交易。其他场景仍返回既有导航结果。

assistant可生成待确认草稿，不执行扣款；最终仍需统一确认、服务端校验与幂等。策略为integrated-demo-1026.1，旧策略确认不可继续执行。公开operations中包含transfer_ops的只读投影，UI不能再本地插入或扣账。名册统一来自recipients.py，phone只是虚构检索信息。


## 当前assistant填表契约（替代上节直接生成preview的描述）

assistant RPC只收集字段。assistant_transfer保存recipient_alias、recipientId、amount_minor、amount_text、currency_text、status，以及表单生成确认后的operation_id。needs_input返回route=transfer-conversation与conclusion；齐全后返回route=transfer-form和transfer字段。此时不创建operations/transfer_ops，不消耗交易授权或扣款。金额以整数分传递，裸数字仅用于当前明确金额追问，并在页面标明按人民币理解。

现有表单propose建立唯一金融操作，再走原确认。RPC assistant的更正使绑定的旧操作失效，即使新金额非法也不恢复旧确认。完整新任务不继承旧字段；非转账任务清理槽位；刷新和助手关闭不会清除服务端槽位。/api/chat保留原协议，最新UI不调用它创建转账。

## 1030 路由与端点核对

本节按实际代码补齐上文未列出的已实现路由，并如实记录与契约不一致处。逐条证据（文件与行号）见 `reports/api-endpoints-1030ver4.json`。

### 幂等键豁免范围（订正）

上文「POST（建立会话除外）必须提供 Idempotency-Key」不完整：`/api/developer/*` 也在键检查之前返回（`first_agent/server.py:78-79` 早于 `:90-91`）。因此实际豁免为 `/api/session` 与 `/api/developer/login|logout|reset|restore`。

### 已实现但上文未列出的路由

| Method | Path | 动作 | 代码位置 |
|---|---|---|---|
| GET | /api/calendar | calendar.list | `first_agent/server.py:41` |
| GET | /api/market/status | market.status | `first_agent/server.py:41` |
| GET | /api/market/context | market.context | `first_agent/server.py:41` |
| GET | /api/recipients | recipients | `first_agent/server.py:41-42` |
| GET | /api/audit/export | audit.export | `first_agent/server.py:42` |
| GET | /api/external/status | external.status | `first_agent/server.py:43` |
| POST | /api/page/open | page.open | `first_agent/server.py:86` |
| POST | /api/calendar/save | calendar.save | `first_agent/server.py:86` |
| POST | /api/calendar/reserve | calendar.reserve | `first_agent/server.py:86` |
| POST | /api/calendar/release | calendar.release | `first_agent/server.py:86` |
| POST | /api/calendar/google/sync | calendar.google.sync | `first_agent/server.py:86` |
| POST | /api/profile | profile.update | `first_agent/server.py:86` |
| POST | /api/market/recommend | market.recommend | `first_agent/server.py:86` |
| POST | /api/external/probe | external.probe | `first_agent/server.py:87` |
| POST | /api/external/search | external.search | `first_agent/server.py:87` |
| POST | /api/local-life/links | local_life.links | `first_agent/server.py:87` |

### 引用原文页

| Method | Path | 用途 | 代码位置 |
|---|---|---|---|
| GET | /review/source/{document_id}#L{line} | 审核链的原文定位页（哈希校验后渲染） | `review_additions/runtime.py:259-266` |
| GET | /relay/source/{version}/{document_id}#L{line} | 接力链的版本化原文页；当接力服务启用时 `/review/source/*` 一律返回 `REVIEW_SOURCE_DENIED` | `relay_additions/runtime.py:99-102` |

### 体验层接口（独立文档）

`GET /api/experience/status`、`POST /api/experience/{consent,events,query,feedback,delete}` 见 `API-EXPERIENCE-1029.md`，实现于 `review_additions/runtime.py:253-296`。本节不重复其字段定义。

### 已知覆盖缺口（如实记录，未擅自改动）

- `start.py`（8798）与 `start_additive_rag.py`（8799）实例化的是原始 `AgentService`，没有挂 `LedgerGateway` 与 `web_security`；当前演示链（8805/8806/8807）才有。
- `/api/developer/*` 在 `service.call` 之前返回，`/api/experience/*` 直接调用 `ExperienceStore`，两者都绕过 `LedgerGateway` 的准入记录。
- `rpc` 白名单上文漏列 `configureSimulation` 与 `assistant`；`first_agent/service.py:33` 实际包含两者。
- `modules/环境生成agent/scenario_server.py` 的独立场景生成服务（默认 8765）不复用本 envelope 的 `trace` 形状，且原注释引用了不存在的 `API-CONTRACT(1).md`。

## 1030 在线核验（knowledge 的可选参数）

`POST /api/knowledge` 增加可选参数 `online_verify`（必须是字面 `true`）。只有本次请求显式传入、且本地知识库判定 `no_evidence` 时，才会访问外网核对官方原文。

- **抓取范围**：只抓该术语在 `knowledge/finance_glossary.json` 里已经声明的 `source_uri`，主机限定 `www.csrc.gov.cn`、`www.gov.cn`、`www.pbc.gov.cn`、`www.nfra.gov.cn`、`guiyang.pbc.gov.cn`；重定向同样受该主机集限制，越界即失败。
- **不发送问题**：请求的是一个固定的官方页面 URL，问题文本不出行。
- **AI 网页版**（`chat.deepseek.com`、`kimi.moonshot.cn`、`yiyan.baidu.com`、`tongyi.aliyun.com`）只作为 `ai_links` 跳转返回，不抓取、不作为引用。
- **返回状态**：`verified`（已取到含术语的原文段落）、`partial`（页面取回但无该术语段落）、`source_unparseable`（来源是 PDF 等无法解析，只给链接）、`no_source`（术语表没有该问题的来源）、`blocked`（隐私过滤或主机不允许）、`unavailable`（网络/解析失败）。
- **引用字段**：`citations[]` 含 `title, section, source_uri, excerpt, publisher, published_at, fetched_at, document_sha256, kind='official_web'`；`excerpt` 永远是官方原文，未经改写。
- **模型改写**：`rewrite = {status, text, label}`，`label` 固定为「模型改写（非引用原文）」。改写要过硬校验（不得出现原文没有的数字/日期、不得声称来源、不超过一句）；任一不满足即丢弃，只保留原文。
- **证据冻结**：每次抓取写 `runtime/online-evidence/<sha256前16位>.json`，含 URL、抓取时间、内容哈希、摘录；**不写问题原文**。
- **边界**：`verified` 只证明官方页面写有该表述，不等于语义正确、也不等于业务适当性通过；`investor.gov` 的 33 条术语不在允许抓取范围，会返回 `blocked` 或 `source_unparseable`。
