"""Detailed branch handoffs, with source comparisons generated from local files."""
from pathlib import Path
import difflib
import hashlib
import json
import re

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent

DETAILS = {
    'eva': r'''
## 选版依据、补丁来源与实际修改位置

1020/ver.2 缺少完整 bank_agent 依赖，不能直接把原 orchestrator 当作可运行入口。集成保留可独立使用的工具、数据、模型和认证契约，缺少的 scanner 从 ver.1 定点补入。所有运行改动位于 FirstAgent；Teammate_output 原件未改。

| 文件 | 处理方式 | 已实施内容及原因 |
|---|---|---|
| `first_agent/vendor/eva/data.py` | 原样复用 ver.2 | 保留 MockBank、Decimal 金额、名册、策略加载与账户归属校验；不把其模拟期初余额合并到 vv 账本。 |
| `first_agent/vendor/eva/tools.py` | 原样复用 ver.2 | 调用 ToolRegistry._validate_transfer 校验账户、收款人、金额及硬限额；没有调用旧 transfer_funds 形成第二份账本。 |
| `first_agent/vendor/eva/models.py` | 原样复用并规范文件名 | 来源 models(3).py，提供 ToolError 等数据类型；文件名规范化不代表模型逻辑重写。 |
| `first_agent/vendor/eva/policy_config.json` | 原样复用 | 保留 eva 单笔、日累计硬限制。集成黄色/红色阈值单独定义，不能误认为配置原值。 |
| `first_agent/vendor/eva/risk/auth.py` | 原样复用 | 使用 StepUpAssertion 数据契约；集成的持久化验证不依赖原内存 consume 流程。 |
| `first_agent/vendor/eva/risk/compliance.py` | 从旧版本原样补缺 | 来源 ver.1/compliance(1).py；新版缺 scanner，补回输入扫描与基础脱敏。 |
| `first_agent/vendor/eva/utils.py` | 新增兼容补丁 | 补 fmt_money，满足原工具的格式化导入，不在此处执行资金计算。 |
| `first_agent/vendor/security/gate.py` | 原样复用项目代码 | 来源 risk_security_toolkit/risk_scaffold/modules/security.py；使用 Principal、ToolPolicy、SecurityGate，默认拒绝未知工具、缺 scope 或越权资源。 |
| `first_agent/security.py` | 新增外层修复 | Scanner.redact_text 先处理密码、password、api key、secret、token 自由文本；redact_obj 递归遮盖认证字段，识别数字型手机号及长数字标识；仅对白名单哈希字段且符合 64 位十六进制格式保留原值，避免审计哈希被误脱敏。 |
| 各 vendor 目录的 __init__.py | 新增包结构 | 使散落交付文件可用包内导入，不改变原业务规则。 |

## service.py 中属于本分工的新增实现

以下方法均位于 `first_agent/service.py`，由集成层实现；交接给 eva 维护安全与业务工具部分，整文件仍与集成负责人共享。

1. `integer`、`canonical`、`digest`：金额边界只接受规定范围的整数分，拒绝 bool/浮点/字符串；规范 JSON 拒绝非有限数字，生成稳定 SHA-256。
2. `require`：将 consent.read 映射到账户、交易与订阅读取 scope，将 consent.trade 映射到转账写 scope；资源归属由服务端会话客户确定。订阅和申赎的具体权限还由 vv 引擎检查。
3. `transfer_policy`：检查任务活动状态、锁定及未知结果；只支持统一转出账户 ACC-4821；把当前 SQLite 余额和当日累计由分转换为 Decimal 元后注入临时 MockBank 校验。原 eva 余额不会成为资金来源。
4. `transfer_preview`、`attach`、`bound_hash`：新增待确认转账，绑定客户、会话、operation、类型、对象、金额、账本版本、策略版本及过期时间；预览 300 秒有效。过期时间使用整数 epoch 秒，修复 Python/JS 浮点序列化导致哈希不同的问题。
5. `check_pending`、`invalidate_transfers`：操作必须仍处于 awaiting_confirmation；过期、参数/版本或策略变化拒绝执行；权限和计划变化后同步失效转账预览。
6. `dispatch` 的 transfer.verify：模拟验证码 246810，错误累计到三次锁定；生成绑定客户、会话、预览哈希的断言，120 秒有效，持久化 consumed 状态。
7. `transfer_confirm`：只接受 confirmed 为 true；确认时重新校验权限、余额及累计。含本次累计不超过 100000 分为黄色，超过为红色；红色还检查 assertion_id、绑定、过期与未消费。消费断言与账本写入在同一事务内。
8. `pending_from_engine_assertion`：为 vv 红色申购/赎回补充断言期限及哈希验证；虽然在引擎调用后检查，但仍在同一数据库事务内，失败会恢复调用前状态，不能留下已扣资金。
9. `apply_transfer`：原子更新 available、initialTotal、version、daily_transfers、回执及负数转账账单；成功清零失败计数、失效其他预览，并把规划总额和配置金额收敛至剩余资金范围；提交前再次运行引擎守恒检查。
10. `transfer_reconcile`：unknown 时不假定成功扣款；阻断后续金融写入，按原 operation 核实 pending/success/failed。确认成功才记账，不能对已核实操作再次核实扣款。
11. `audit`、`public_state`：审计参数和错误经 Scanner 处理；公开快照移除 session_id 和嵌套 assertion。该处理不等于所有响应字段都已做生产级隐私审查。

## 接口变化与交接约束

- 转账统一使用 `/api/transfers/preview`、`verify`、`confirm`、`reconcile`、`cancel`，参数和错误见 `API-CONTRACT.md`；金额字段 amount_minor 为整数分。
- 认证、预览、幂等回执和累计都依赖同一会话数据库。不能把原 ver.2 工具内存状态直接替换进执行路径。
- P01 为缺失编排补位，P04 为 scanner/gate/断言补丁，P06 为统一契约；完整来源和目标哈希见 `reports/patch_manifest.json`。
- 团队交付模拟银行 API；真实银行对接由组委会部署时处理。演示认证仍需明确标识，真实 MFA 不是本次团队必须补接的银行服务。

## 验证依据与未完成项

既有集成测试覆盖缺权限、未知工具、账户归属、跨会话、金额类型、累计红色阈值、预览过期/撤权/暂停、断言超时回滚、三次失败锁定、线程和多进程只扣一次、脱敏与合法哈希保留。具体测试函数见 `tests/test_integration.py`；这是新的集成测试，不是 eva 原版 42 项测试复跑。

## 卡管理模块的后续需求（尚未实现）

原始要求（GPT 补入 eva.md）：卡管理相关模块还要参考真实银行APP的模式进行修改，需要一个从卡库里选择卡的功能。

卡状态查询和冻结工具在 eva 原件中存在，但 FirstAgent 尚无完整卡管理路由、持久状态和前端闭环。以下为后续需求与分工建议，不能写成已完成改动：

- 参考真实银行 APP 的卡管理模式：先展示当前客户名下的卡列表或卡库，再由用户选中具体卡进行操作，不采用自由输入卡号的方式。
- 新增“从卡库里选择卡”的能力：卡库返回卡 ID、卡种、尾号、状态及可用额度/余额等字段；服务端必须校验卡归属、卡状态和操作权限。
- 补齐卡状态查询、冻结/解冻、申请、挂失等流程的 API 契约、持久状态、权限 scope、幂等回执、审计和前端选择交互；卡操作沿用统一状态与错误模型。
- 主责建议 eva（后端卡库与卡管理 API/工具），vv 负责卡列表与选择交互，集成负责编排、权限和事务安全，YUKI 负责知识说明与验收。
- 当前 API-CONTRACT.md 未定义卡管理端点，现有测试也未覆盖卡管理，不能声称已可调用；原包缺失依赖与原版测试仍需 eva 整理补交。
''',
    'vv': r'''
## 选版依据与界面保留范围

采用 1021 最新独立 HTML 对应的源码。两段业务脚本与独立 HTML 比对一致；非字体 CSS 一致，因此使用可维护的拆分文件结构。四主导航、原有账单、订阅、预演、申购赎回界面保留。原输出文件未改，修改在 FirstAgent/web。

## 逐文件改动

| 文件 | 处理方式 | 已实施内容及原因 |
|---|---|---|
| `web/index.html` | 新增集成入口 | 加载顺序改为 server-bridge.js → journey-workspace.js → agent-panel.js，浏览器不再直接加载业务引擎；保留 CSS、字体预加载和 noscript 提示。 |
| `web/journey-engine.js` | 修改原引擎 | createSession(saved) 深拷贝恢复服务器快照；根据 operations/events/positions 的已有 ID 恢复 serial；新增 initialTotal 守恒基准，替代固定 12864000；期限判断改为锁定月数×30+1 个结算日不超过目标月数×30。 |
| `first_agent/engine_worker.cjs` | 新增服务器执行桥 | 从 stdin 读取 state/method/args，一次进程执行一次确定性方法；stdout 输出 state/catalog/total/capacity/result/error。无 shell 拼接或 eval。 |
| `web/server-bridge.js` | 新增兼容层 | 先建立/复用会话再读 snapshot，保留 window.BankCore.createSession 调用外形；state/catalog 返回副本；业务方法转发 /api/rpc，每次 POST 使用 UUID 幂等键，并在 finally 刷新快照。 |
| `web/server-bridge.js` 的 summary | 启动问题修复 | 总览直接汇总已交付给演示所有者的快照，避免启动阶段未授权 Agent 读取导致页面报错；服务端账户与分析查询仍要求 read 权限。 |
| `web/journey-workspace.js` | 修改入口和部分能力文案 | 转账卡改为“本地模拟”，姓名转账标为可用，手机号/定时/AA 保留未实现；助手与转账入口转到新面板；页脚改为本地持久化；重置主按钮及确认弹窗改为刷新保留。 |
| `web/agent-panel.js` | 新增对话与转账面板 | 注入面板样式与入口；显式授权、对话、计划展示、转账预览、红色模拟验证码、确认/取消、未知回执查询、审计和转账记录恢复；结果用 textContent 展示；inflight 限制发送/确认连点。 |
| `web/journey-workspace.css`、`web/fonts/` | 复用资源 | 保留原界面样式和字体/许可资料；新面板样式位于 agent-panel.js，未重写原 CSS 主题。 |
| `tests/vv_core.cjs` | 修改原测试适配 | require 路径从 ../dist 改到 ../web；TERM6 在六个月目标下因额外结算日改判不符合，其他 15 项用例结构沿用。 |

## 状态、金额与交互接入变化

1. 页面原内存账本改为 SQLite 服务端权威状态；刷新、服务重启仍可恢复同一 cookie 会话。银行引擎每次由 Node 在服务端运行，页面只拿快照。
2. `bank-ledger-refresh` 事件刷新快照并触发 hashchange 重绘；转账成功同步总览、账单和配置资金。`total`、`capacity` 来自服务端快照，monthlySaved 由快照订阅汇总。
3. 新面板以 fetch 调用 `/api/chat`、转账系列、`/api/events`、`/api/snapshot`；界面金额由整数分除以 100 展示，发送 amount_minor 等接口字段时保持整数分。
4. 查看转账记录会找回 awaiting_confirmation/unknown 操作，分别恢复确认或查询入口；新会话拥有独立虚构账本。
5. 既有申赎预览增加服务器绑定和 TTL，失败、过期、撤权后不能只凭浏览器快照执行；服务器对兼容 RPC 使用白名单。
6. P03 记录前后端接入补丁，P06 记录统一契约。共享 service.py 的具体事务、转账入账和推荐适配见 integration/eva/Ethan 交接，不复制第二套规则到界面。

## 已验证与准确边界

既有 15 项规则检查通过。浏览器验证过 800 元转账后余额 38640→37840 元、总资产 128640→127840 元、账单支出增加 800 元，刷新与服务重启保留；债务比率和恢复的流动性资料可展示引用。证据见 `reports/verification.json`、`reports/browser-verification.json`。

本次核对发现仍有旧辅助文案：授权面板还写“本页会话，刷新清空”，沙箱设置主按钮虽已改成刷新保留，下方 help 仍写清空。这两处尚未修改，不能声称所有文案都已同步。同步 XHR 会阻塞主线程；转账记录仍在助手面板；全尺寸及无障碍验收尚未完成。卡管理界面未实现，后续与 eva 的模拟卡 API 对接。
''',
    'YUKI': r'''
## 选版、缺失判断及补丁依据

1022 最新 ZIP 有 19 个有效文件，已有解压目录只有 15 个；仅看解压目录会误判三篇知识缺交。排除 __MACOSX 后从 ZIP 恢复现金流、储蓄率、流动性及银行业务知识库说明。恢复的是队友已交付内容，不是集成时编造的银行知识。原目录未改。

原 simple_RAG 会给无关文档附加分数，长中文句子的检索和来源表示也不足。保留它作为参考源码，实际运行复用项目 RAG/banking_rag，使用 BM25、中文双字分词和可核查证据。补丁编号 P05。

## 逐文件与逐模块记录

| 文件/目录 | 处理方式 | 已实施内容 |
|---|---|---|
| `sources/YUKI/` | 来源快照及 ZIP 恢复 | 保存 README、说明、评测题库、simple_RAG.py 和资料原件；历史乱码文件保留用于核对，不全量直接扫描进运行知识库。 |
| `knowledge/01-现金流.md` | 从 ZIP 补回 | 原解压目录缺失，按正文标题恢复可读文件名；原文字节及哈希保留。 |
| `knowledge/02-储蓄率.md` | 从 ZIP 补回 | 同上，已入索引，不再列为缺失主题。 |
| `knowledge/03-流动性.md` | 从 ZIP 补回 | 同上，已由自动化及浏览器验证检索。 |
| `sources/YUKI/docs/银行业务知识库.md` | 从 ZIP 补回 | 恢复资料总说明，作为交接来源文档，不计为第九篇运行知识。 |
| `knowledge/04-债务比率.md`、`knowledge/05-风险管理.md` | 规范运行副本文件名 | 按正文标题命名，保留最新原文；未改写公式或添加现实银行规则。 |
| `knowledge/06-合规边界.md`、`knowledge/07-订阅管理.md`、`knowledge/08-旅行预算.md` | 规范运行副本文件名 | 同上，总计八篇显式入库资料。 |
| `knowledge/manifest.json` | 新增清单 | 为八篇文档登记 id/path/title/kind/revision/source_uri/sha256/valid_from/valid_until；来源精确到 ZIP 内 entry，kind 标为 educational_demo，未确认的有效期保留 null。 |
| `knowledge/index.json` | 构建索引 | 由显式 manifest 建索引，保留分块、行号、文档哈希及检索信息；文件名恢复不改变原文哈希。 |
| `first_agent/vendor/rag/corpus.py` | 原样复用 | 显式资料导入、哈希校验、路径检查、保留行号分块及索引写入。 |
| `first_agent/vendor/rag/retrieval.py` | 原样复用 | BM25 和中文检索；不是本轮重写排序算法。 |
| `first_agent/vendor/rag/service.py` | 原样复用并接入 | 离线摘录、grounded/no_evidence、业务数据边界及引用结构；本次没有配置生成模型客户端。 |
| `first_agent/vendor/rag/providers.py`、cli.py、__main__.py、__init__.py | 原样保留包内容 | 保持原项目包结构及可选扩展入口；不代表已经启用外部模型或逐个 CLI 验收。 |
| `first_agent/service.py` | 新增业务接线 | 初始化 RAGService；缺 index 时按 manifest 构建；knowledge 动作调用 ask 并添加教育演示提示；chat 非业务查询回退到知识检索。 |
| `web/agent-panel.js` | 共享前端展示 | 展示回答、证据与引用 JSON；界面实现归 vv，资料正确性由 YUKI 维护。 |

## 接口与能力边界

- `POST /api/knowledge` 输入 question/top_k，金融响应外壳与 RAG 的 data.status 分开；引用包含来源、文档哈希及行号。没有依据时返回 no_evidence，不编造答案。
- 个人余额/交易事实通过业务工具读取，知识资料不会触发转账或写操作。chat 的规则仍按关键词路由；例如含“现金流”的问题可能进入账单工具，并未实现任意语义问题分类。
- 运行资料由 manifest 显式选取，sources 中乱码/可读双副本不会重复入库。八篇原文列表和逐项哈希见 `knowledge/manifest.json`；四个恢复文件及完整 ZIP entry 清单见 `reports/yuki-archive-recovery.json`。

## 验证与后续交接

既有 test_rag_sources_no_evidence_and_no_side_effect 覆盖原文引用、无关问题和不改余额；test_recovered_archive_knowledge_is_indexed 覆盖恢复内容；浏览器记录覆盖债务比率和流动性引用。此前 20 正常、20 边界、10 风险评测题仍是队友题库，未声称 50 题全部自动评分通过。

后续补充资料审核人、适用期和明确来源，完善评测标注与自动评分。现金流、储蓄率、流动性已恢复，应从旧“缺失”清单移除。真实银行条款与真实 API 由组委会接入阶段提供；当前资料只按教育演示标注。
''',
    'Ethan': r'''
## 归属与补位依据

Ethan output 为空，无法依据文件确认 Ethan 原定职责或选取其最新代码。因此此文档是“空交付补位”的交接，不把推荐模块归属当成已确认的人事分工。为首版提供可运行推荐，复用项目 financial_recommendation_module；补丁编号 P02。

## 逐文件改动与原样复用

| 文件 | 处理方式 | 已实施内容及原因 |
|---|---|---|
| `first_agent/vendor/finance/matching_core.py` | 原样复用 | 保留原有资格校验、风险/期限/金额/产品事实约束；没有重写核心评分算法。 |
| `first_agent/vendor/finance/rule_driven.py` | 单项代码修改 | from matching_core 改为 from .matching_core，使模块放入 vendor.finance 后可包内导入；其 recommend 被实际运行调用。 |
| `first_agent/vendor/finance/data_driven.py` | 单项代码修改 | 同样修正包内导入；保留作为参考/扩展代码，首版未调用数据驱动模型进行推荐，也未训练模型。 |
| `first_agent/vendor/finance/__init__.py` | 新增包入口 | 支持服务端相对导入。 |
| `first_agent/service.py` 的 recommendations | 新增统一适配 | 将 vv 当前产品目录映射到原推荐模型，并以当前用户状态、配置资金和目标期限构造 profile。 |
| `tests/test_integration.py` | 新增集成验证 | test_recommendation_consistency_and_profile_missing 核对目录/金额/期限及资料缺失行为。 |

## recommendations 适配的全部字段与行为

1. 产品 ID/name/risk 分别映射 product_id/name/risk_level；p.min 从整数分转 min_investment_cny 元。API 和账本仍使用整数分，仅适配层转成推荐模块所需单位。
2. p.term 月按 30 天转 lockup_days，redemption_days 固定 1；用款 horizon_days 为目标月数×30，使推荐与引擎都计入结算等待日。
3. 非锁定产品归 cash/liquidity，其余归 fixed_income/income；沿用同一份 vv 目录，不独立创建另一套可购买产品。
4. redemption 为 unsupported 的产品标记 facts_verified=false、annual_fee_pct=None；其余为当前虚构目录的演示值，不代表真实银行费用。
5. profile 为 valid 时 risk_tolerance=1，否则设 None；risk_capacity=1，不能靠输入任意偏好提高当前风险权限。缺档案时返回 needs_profile_completion。
6. budget_cny 使用 min(state.amount, engine.capacity)/100，避免推荐金额超出当前配置或扣除必要用款、应急金后的资金。
7. objective 接受调用参数，默认 liquidity；preferred_categories 为 cash，top_k 默认 3；输出补 money_unit 说明适配单位。使用规则 recommend，不产生自动申购。
8. 服务通过 `/api/products`、`/api/recommendations` 及 chat 的推荐动作暴露结果；真正执行仍走 vv 资格校验、预览与确认，不把推荐结果当授权。

## 验证与待交接项

既有测试验证推荐使用相同目录、金额和期限，配置金额较低时排除不满足起点的产品，六个月目标不能容纳六个月锁定再加一天结算，档案缺失时请求补资料。记录见 `reports/verification.json`。data_driven 未运行，不能把规则集成的通过结果算成其模型质量验证。

Ethan 仍需补交原职责、完整 output、测试和依赖说明；确认推荐职责归属后再认领该补位模块。团队目前只需要模拟产品和银行 API；真实产品映射由后续组委会接入处理。
''',
    'integration': r'''
## 架构补位依据与修改边界

原 Orchestrator/agent_orchestrator.py 为 0 字节，eva 编排包又缺关键依赖，不能直接拼接运行。新增 FirstAgent 集成包，用 vv 业务引擎作为唯一模拟账本规则来源，以 SQLite 持久化状态，接入 eva 校验、项目推荐与 RAG。原始协作产出不回写；P01/P03/P04/P05/P06 的来源见 `reports/patch_manifest.json`。

## 新增服务与逐方法改动

`first_agent/service.py` 整体为新增集成实现，按职责拆分如下；安全细节见 eva，推荐细节见 Ethan，知识接入见 YUKI。

| 方法/常量 | 已实施内容 |
|---|---|
| SCHEMA / POLICY_VERSION / METHODS / READ | 固定响应版本与演示策略版本，限制 RPC 方法白名单及读取动作权限。 |
| canonical / digest / stamp / integer / Fault | 稳定 JSON、哈希、UTC 审计时间、整数分校验、统一业务异常。 |
| __init__ | 检查 Node；创建 sessions/requests/audit 表；用 closing 关闭初始化数据库连接，修复 Windows 句柄占用；初始化 RAG 和安全 gate。 |
| connect / transaction | SQLite WAL、20 秒等待、BEGIN IMMEDIATE；成功 commit、异常 rollback、finally close，串行化共享数据库的修改。 |
| engine / engine_call | subprocess 参数数组启动 Node worker，JSON stdin/stdout，15 秒超时；接收新状态和业务结果；策略错误需保留的锁定/失败计数显式持久化。 |
| create_session / load | 服务端随机会话，当前演示客户 CUST-001；初始化 transfer_ops/daily_transfers/task_log/clarification；无效会话拒绝。 |
| audit / envelope / require | 参数脱敏后同事务写审计；统一 schema_version/request_id/status/data/error/trace/simulated；scope 与客户资源检查。 |
| call | 哈希绑定 action+args；同会话同幂等键同请求返回原响应，改参冲突拒绝；业务异常按 persist 标志保留或恢复状态；状态、审计、幂等响应一起提交。 |
| pending / bound_hash / attach / check_pending | 定位当前会话操作、预览绑定、300 秒 TTL 与失效检查。 |
| invalidate_transfers / pending_from_engine_assertion / public_state | 转账预览失效同步；引擎红色操作补充断言过期检查；快照移除 session_id 和嵌套 assertion。 |
| dispatch | 白名单 RPC、snapshot、accounts、transactions、subscriptions、recommend、knowledge、转账全流程、operation、chat、events 分发；最多返回当前会话 100 条审计；没有动态执行任意工具。 |
| transfer_policy / transfer_preview / transfer_confirm | 临时 eva 校验适配唯一余额；创建绑定预览；明确确认和模拟断言；success/failed/unknown 三种结果。 |
| apply_transfer / transfer_reconcile | 外部转出同步账本总额、累计、回执和账单；unknown 核实原操作后记账，不重复发起。 |
| recommendations | vv 目录和 profile 转原推荐契约，金额/风险/期限与执行侧保持一致。 |
| chat | 1–2000 字符、输入扫描、他人账户关键词拒绝；转账姓名/金额缺失或多个候选时澄清并持久保存；取消待澄清请求；账户、账单、订阅、推荐多工具只读编排及 plan/depends_on；其余进入知识检索；对话不自动扣款。 |

## HTTP 服务、浏览器与启动文件

| 文件/区域 | 新增或修改内容 |
|---|---|
| `first_agent/server.py` / make_server | 标准库 ThreadingHTTPServer，默认仅 127.0.0.1；封装 Handler，主入口提供 --port/--db。 |
| send_json / sid / safe_host | UTF-8 JSON、no-store/nosniff、HttpOnly/SameSite=Strict cookie；会话读取；本机 Host 与 Origin 校验。 |
| do_GET | health、snapshot、账户/账单/订阅/产品/审计、operation 路由；静态文件解析后必须仍在 web 内，防止路径穿越。 |
| do_POST | application/json、1–65536 字节、根对象及非有限数字校验；session 复用有效 cookie；其他 POST 强制 Idempotency-Key；异常不输出内部堆栈。 |
| `first_agent/engine_worker.cjs` | Node 服务端执行原 vv 引擎；每事务一请求，详见 vv 文档。 |
| `first_agent/security.py`、vendor 各包 | 新 scanner 外层修复、包结构补齐及原有组件适配；原样复用与逻辑修改在各分工中分开记录。 |
| `first_agent/__init__.py`、`first_agent/vendor/__init__.py` | 新增包入口，使 python -m first_agent.server 可执行。 |
| `run_agent.ps1` | 定位自身目录后运行 python -m first_agent.server --port 8765。 |
| `README.md` | 运行环境、启动和验证方法、会话持久化、模拟验证码、交付入口及已实现边界。 |
| `API-CONTRACT.md` | 统一整数分、天/月转换、模拟/真实时钟、响应结构、权限、幂等、HTTP 路由、RPC 白名单、状态机与失败/未知语义。 |

## 验证代码与实际验证范围

`tests/test_integration.py` 为新增集成测试，使用临时 SQLite、可注入时钟、线程与进程池及 HTTP cookie 客户端；不以真实银行为依赖。共 20 项：默认拒绝/未知工具；跨会话隔离；单账本幂等持久恢复；金额及归属；累计红色验证；预览过期/撤权/暂停；未知阻断和核实；线程只提交一次；多进程只提交一次；订阅取消与申购同账本；申购断言超时回滚；赎回恢复及结算；RAG 证据/无证据/无副作用；ZIP 恢复资料入索引；多轮多工具；歧义金额；推荐一致性/缺档案；脱敏保留哈希；三次失败锁定；HTTP cookie/Origin/静态文件/刷新。

`tests/vv_core.cjs` 沿用 15 项规则检查，修改加载路径和六个月结算边界；详见 vv。`verify_delivery.py` 新增统一运行入口，收集 Python 与 Node 结果，生成 integration-tests.txt、vv-tests.json、verification.json；失败返回非零退出码。

既有报告为 20+15 项通过，验证时间见 `reports/verification.json`；浏览器额外验证模拟转账、账单联动、刷新和服务重启持久恢复、知识引用。当前文档续作未重新运行业务测试，不能把旧时间标成新的测试时间。

## 来源盘点、报告与本次文档修改

- `.work/build_first_agent.py`（位于项目根目录）是首轮组装脚本：盘点 output、选择并复制来源、解压与整理运行资产。它不是最终增量迁移器，重跑可能覆盖后续修复，交接时应以 FirstAgent 当前代码为准。
- sources/ 保留各分工参考快照；source_inventory 记录源文件时间、大小、哈希；archive-comparison、vv-style-comparison、yuki-archive-recovery 记录内容比较及恢复事实。
- `write_reports.py` 生成总版、上下文、补丁映射、各分工文档和交付哈希清单。本次接入 `write_branch_details.py`，使重新生成报告也能保留逐文件明细、原样复用表和实际源差异。
- `write_branch_details.py` 为本次新增文档生成代码：按职责记录所有新增方法及改动，直接比较参考源/运行文件生成 diff；复用文件同时核验 SHA-256；自动链接本地文件。
- 本次修正 YUKI 已恢复资料仍写缺失的问题，并明确卡管理尚未接入；同步真实银行由组委会接入的交付边界。
- 额度规则按用户最新指示仅监测 windowDurationMins=300 的 5h 窗口；剩余严格小于 10% 停止，周额度不参与停止。工具只提供采样快照，不能宣称实时推送。历史周额度中止仍保留为历史记录，当前规则覆盖旧规则。
- context_log.md/json 保存此前中止记录及续作，summary.md/json 和五份分支文档同步；file_manifest.json 在报告写完后重建，不包含 runtime、缓存及清单自身。

## 后续边界与责任

团队交付本地模拟银行 API、清晰接口契约和可替换接入边界；组委会负责真实银行部署接入。现有 service.py 仍直接组合 MockBank 与 Node，并没有已经完成的独立 BankAdapter 插件系统，不能把可替换设计目标写成已存在的类。

尚未实现完整卡管理、手机号/定时/AA 转账、自动订阅识别提醒、生日商户联动及开放式模型。卡管理建议 eva 负责后端、vv 负责界面、集成负责编排安全、YUKI 负责说明与验收；Ethan 原职责待确认。同步 XHR、有限规则理解、演示会话认证和本地审计均有明确适用范围。
''',
}

def file_link(path, label=None):
    return f'[{label or path.name}](<{path.resolve().as_posix()}>)'

def link_paths(text):
    def replace(match):
        value = match.group(1)
        for base in (BASE, ROOT):
            path = base / value
            if '/' in value and path.exists():
                return file_link(path, value)
        return match.group(0)
    return re.sub(r'`([^`\n]+)`', replace, text)

def comparisons(name):
    if name == 'eva':
        pairs = [(BASE/'sources/eva'/src, BASE/'first_agent/vendor/eva'/dst) for src, dst in
                 [('data.py','data.py'),('tools.py','tools.py'),('models(3).py','models.py'),
                  ('policy_config.json','policy_config.json'),('auth.py','risk/auth.py')]]
        pairs += [(ROOT/'Teammate_output/eva output/1020/ver.1/compliance(1).py', BASE/'first_agent/vendor/eva/risk/compliance.py'),
                  (ROOT/'risk_security_toolkit/risk_scaffold/modules/security.py', BASE/'first_agent/vendor/security/gate.py')]
        return pairs
    if name == 'vv':
        return [(BASE/'sources/vv'/src, BASE/dst) for src, dst in
                [('dist/journey-engine.js','web/journey-engine.js'),('dist/journey-workspace.js','web/journey-workspace.js'),
                 ('dist/journey-workspace.css','web/journey-workspace.css'),('tests/core.cjs','tests/vv_core.cjs')]]
    if name == 'Ethan':
        return [(ROOT/'financial_recommendation_module'/n, BASE/'first_agent/vendor/finance'/n)
                for n in ['matching_core.py','rule_driven.py','data_driven.py']]
    if name == 'YUKI':
        return [(ROOT/'RAG/banking_rag'/p.name, p) for p in sorted((BASE/'first_agent/vendor/rag').glob('*.py'))]
    return []

def render_branch(branch):
    name = branch['file']
    parts = ['# '+branch['branch_name']+'：代码修改明细',
             '记录范围：首次集成已实施修改及本次文档补全。依据、修改与验证先列，结论置于末尾。原输出目录未改；共享 service.py 按职责分别说明。',
             DETAILS[name].strip(), '## 可核对的来源差异']
    pairs = comparisons(name)
    if pairs:
        parts += ['下表由当前来源副本与运行文件逐字节比较生成。相同表示原样复用，不计为逻辑修改。',
                  '| 来源 | 运行文件 | 字节比较 |', '|---|---|---|']
        for source, target in pairs:
            same = source.read_bytes() == target.read_bytes()
            parts.append(f'| {file_link(source)} | {file_link(target)} | '+('相同' if same else '有差异')+' |')
        for source, target in pairs:
            if source.read_bytes() == target.read_bytes():
                continue
            diff = ''.join(difflib.unified_diff(source.read_text(encoding='utf-8-sig').splitlines(True),
                           target.read_text(encoding='utf-8-sig').splitlines(True),
                           fromfile=source.as_posix(), tofile=target.as_posix(), n=2))
            parts += ['### '+target.name+' 的完整文本差异', '```diff\n'+diff.rstrip()+'\n```' if diff else '文本相同；字节差异来自编码或换行表示。']
    else:
        parts.append('service.py、server.py、security.py、engine_worker.cjs、HTTP 集成测试及交付脚本均为新增集成文件；不存在完整旧实现可作逐行 diff。新增职责已在前文逐方法列出。')
    if name == 'YUKI':
        manifest = json.loads((BASE/'knowledge/manifest.json').read_text(encoding='utf-8'))
        parts += ['### 八篇原文哈希核对', '| 运行原文 | SHA-256 | 与清单一致 |', '|---|---|---|']
        for doc in manifest['documents']:
            path = BASE/'knowledge'/doc['path']
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            parts.append(f'| {file_link(path)} | `{actual}` | '+('是' if actual == doc['sha256'] else '否')+' |')
    parts += ['## 测试与报告入口',
              '此前验证报告：'+file_link(BASE/'reports/verification.json')+'；浏览器证据：'+file_link(BASE/'reports/browser-verification.json')+'。本次只核对来源、文档覆盖和报告生成，不冒称重跑业务测试。',
              '统一接口：'+file_link(BASE/'API-CONTRACT.md')+'；补丁来源：'+file_link(BASE/'reports/patch_manifest.json')+'；交付文件哈希：'+file_link(BASE/'reports/file_manifest.json')+'。',
              '结论：本分工的已实施修改、原样复用、补丁来源、接口影响、验证依据与尚未完成项已分开记录；后续协作以当前 FirstAgent 代码及统一契约为准。']
    # Link authored paths before adding generated diffs, so diff contents stay exact.
    parts[2] = link_paths(parts[2])
    return re.sub(r'(?m)(^\|[^\n]*\|)\n\n(?=\|)', r'\1\n', '\n\n'.join(parts))+'\n'
