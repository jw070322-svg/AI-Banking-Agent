# SecondAsgent 统一接口（响应 1.0.0；策略 integrated-demo-1.1）

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
| GET | /api/health | ready, persistent, mode | 服务健康 |
| GET | /api/snapshot | state, catalog, total, capacity | 当前演示所有者快照 |
| GET | /api/accounts/overview | available_minor, positions_minor, total_minor, version | Agent 查询需 read |
| GET | /api/transactions?month=2026-10 | items, summary | 需 read；聚合结果为整数分 |
| GET | /api/subscriptions | 虚构订阅数组 | 需 read |
| GET | /api/products | 推荐结果及排除理由 | 教育演示目录 |
| POST | /api/recommendations | objective, top_k | 同一目录、金额、期限、风险适配 |
| POST | /api/knowledge | question, top_k | BM25 原文证据，拒绝无证据生成 |
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

## 独立场景生成

POST /api/scenarios/generate，body 为 {"requirement":"最近2个月支出增加800元的用户"}，要求会话和 Idempotency-Key。成功 data 包含 schema_version:"scenario-1.0"、scenario_id、scenario_type、accounts、transactions、warnings、simulated:true、ledger_modified:false。无需金融写入权限，因为不改变客户账本。

accounts 为 account_id、initial_balance_minor、balance_minor、currency；transactions 为 id、account_id、date、amount_minor、category、status。收入正、支出负；completed 映射 booked，rejected 不计余额。拒绝重复 ID、无效关联、非有限/超过两位小数金额及余额不平，错误 SCENARIO_INVALID。输入 1–2000 字符；单个源金额不超过 1,000,000,000 分。不返回源格式中的身份信息，不导入当前会话。

## 接入分工

团队维护模拟 API 与可替换契约；真实银行由组委会本地部署接入。eva 主责卡后端/风控，vv 主责交互，集成负责状态和回执，Ethan 提供场景，YUKI 维护知识与评测。

结论：新增卡管理与场景沿用统一外壳及整数分契约；金融业务共享账本，独立场景不改变实时资金。
