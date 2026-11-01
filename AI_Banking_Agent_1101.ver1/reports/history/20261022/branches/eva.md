# eva / 风控与业务工具：代码修改明细

记录范围：首次集成已实施修改及本次文档补全。依据、修改与验证先列，结论置于末尾。原输出目录未改；共享 service.py 按职责分别说明。

## 选版依据、补丁来源与实际修改位置

1020/ver.2 缺少完整 bank_agent 依赖，不能直接把原 orchestrator 当作可运行入口。集成保留可独立使用的工具、数据、模型和认证契约，缺少的 scanner 从 ver.1 定点补入。所有运行改动位于 FirstAgent；Teammate_output 原件未改。

| 文件 | 处理方式 | 已实施内容及原因 |
|---|---|---|
| [first_agent/vendor/eva/data.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/data.py>) | 原样复用 ver.2 | 保留 MockBank、Decimal 金额、名册、策略加载与账户归属校验；不把其模拟期初余额合并到 vv 账本。 |
| [first_agent/vendor/eva/tools.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/tools.py>) | 原样复用 ver.2 | 调用 ToolRegistry._validate_transfer 校验账户、收款人、金额及硬限额；没有调用旧 transfer_funds 形成第二份账本。 |
| [first_agent/vendor/eva/models.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/models.py>) | 原样复用并规范文件名 | 来源 models(3).py，提供 ToolError 等数据类型；文件名规范化不代表模型逻辑重写。 |
| [first_agent/vendor/eva/policy_config.json](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/policy_config.json>) | 原样复用 | 保留 eva 单笔、日累计硬限制。集成黄色/红色阈值单独定义，不能误认为配置原值。 |
| [first_agent/vendor/eva/risk/auth.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/risk/auth.py>) | 原样复用 | 使用 StepUpAssertion 数据契约；集成的持久化验证不依赖原内存 consume 流程。 |
| [first_agent/vendor/eva/risk/compliance.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/risk/compliance.py>) | 从旧版本原样补缺 | 来源 ver.1/compliance(1).py；新版缺 scanner，补回输入扫描与基础脱敏。 |
| [first_agent/vendor/eva/utils.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/utils.py>) | 新增兼容补丁 | 补 fmt_money，满足原工具的格式化导入，不在此处执行资金计算。 |
| [first_agent/vendor/security/gate.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/security/gate.py>) | 原样复用项目代码 | 来源 risk_security_toolkit/risk_scaffold/modules/security.py；使用 Principal、ToolPolicy、SecurityGate，默认拒绝未知工具、缺 scope 或越权资源。 |
| [first_agent/security.py](<F:/AI_Banking/FirstAgent/first_agent/security.py>) | 新增外层修复 | Scanner.redact_text 先处理密码、password、api key、secret、token 自由文本；redact_obj 递归遮盖认证字段，识别数字型手机号及长数字标识；仅对白名单哈希字段且符合 64 位十六进制格式保留原值，避免审计哈希被误脱敏。 |
| 各 vendor 目录的 __init__.py | 新增包结构 | 使散落交付文件可用包内导入，不改变原业务规则。 |

## service.py 中属于本分工的新增实现

以下方法均位于 [first_agent/service.py](<F:/AI_Banking/FirstAgent/first_agent/service.py>)，由集成层实现；交接给 eva 维护安全与业务工具部分，整文件仍与集成负责人共享。

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
- P01 为缺失编排补位，P04 为 scanner/gate/断言补丁，P06 为统一契约；完整来源和目标哈希见 [reports/patch_manifest.json](<F:/AI_Banking/FirstAgent/reports/patch_manifest.json>)。
- 团队交付模拟银行 API；真实银行对接由组委会部署时处理。演示认证仍需明确标识，真实 MFA 不是本次团队必须补接的银行服务。

## 验证依据与未完成项

既有集成测试覆盖缺权限、未知工具、账户归属、跨会话、金额类型、累计红色阈值、预览过期/撤权/暂停、断言超时回滚、三次失败锁定、线程和多进程只扣一次、脱敏与合法哈希保留。具体测试函数见 [tests/test_integration.py](<F:/AI_Banking/FirstAgent/tests/test_integration.py>)；这是新的集成测试，不是 eva 原版 42 项测试复跑。

## 卡管理模块的后续需求（尚未实现）

原始要求（GPT 补入 eva.md）：卡管理相关模块还要参考真实银行APP的模式进行修改，需要一个从卡库里选择卡的功能。

卡状态查询和冻结工具在 eva 原件中存在，但 FirstAgent 尚无完整卡管理路由、持久状态和前端闭环。以下为后续需求与分工建议，不能写成已完成改动：

- 参考真实银行 APP 的卡管理模式：先展示当前客户名下的卡列表或卡库，再由用户选中具体卡进行操作，不采用自由输入卡号的方式。
- 新增“从卡库里选择卡”的能力：卡库返回卡 ID、卡种、尾号、状态及可用额度/余额等字段；服务端必须校验卡归属、卡状态和操作权限。
- 补齐卡状态查询、冻结/解冻、申请、挂失等流程的 API 契约、持久状态、权限 scope、幂等回执、审计和前端选择交互；卡操作沿用统一状态与错误模型。
- 主责建议 eva（后端卡库与卡管理 API/工具），vv 负责卡列表与选择交互，集成负责编排、权限和事务安全，YUKI 负责知识说明与验收。
- 当前 API-CONTRACT.md 未定义卡管理端点，现有测试也未覆盖卡管理，不能声称已可调用；原包缺失依赖与原版测试仍需 eva 整理补交。
- 加油加油在orchestrator那一块添加一下这块，上面都是我和claude讨论过的还需要小小补一下的内容

## 可核对的来源差异

下表由当前来源副本与运行文件逐字节比较生成。相同表示原样复用，不计为逻辑修改。

| 来源 | 运行文件 | 字节比较 |
|---|---|---|
| [data.py](<F:/AI_Banking/FirstAgent/sources/eva/data.py>) | [data.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/data.py>) | 相同 |
| [tools.py](<F:/AI_Banking/FirstAgent/sources/eva/tools.py>) | [tools.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/tools.py>) | 相同 |
| [models(3).py](<F:/AI_Banking/FirstAgent/sources/eva/models(3).py>) | [models.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/models.py>) | 相同 |
| [policy_config.json](<F:/AI_Banking/FirstAgent/sources/eva/policy_config.json>) | [policy_config.json](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/policy_config.json>) | 相同 |
| [auth.py](<F:/AI_Banking/FirstAgent/sources/eva/auth.py>) | [auth.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/risk/auth.py>) | 相同 |
| [compliance(1).py](<F:/AI_Banking/Teammate_output/eva output/1020/ver.1/compliance(1).py>) | [compliance.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/eva/risk/compliance.py>) | 相同 |
| [security.py](<F:/AI_Banking/risk_security_toolkit/risk_scaffold/modules/security.py>) | [gate.py](<F:/AI_Banking/FirstAgent/first_agent/vendor/security/gate.py>) | 相同 |

## 测试与报告入口

此前验证报告：[verification.json](<F:/AI_Banking/FirstAgent/reports/verification.json>)；浏览器证据：[browser-verification.json](<F:/AI_Banking/FirstAgent/reports/browser-verification.json>)。本次只核对来源、文档覆盖和报告生成，不冒称重跑业务测试。

统一接口：[API-CONTRACT.md](<F:/AI_Banking/FirstAgent/API-CONTRACT.md>)；补丁来源：[patch_manifest.json](<F:/AI_Banking/FirstAgent/reports/patch_manifest.json>)；交付文件哈希：[file_manifest.json](<F:/AI_Banking/FirstAgent/reports/file_manifest.json>)。

结论：本分工的已实施修改、原样复用、补丁来源、接口影响、验证依据与尚未完成项已分开记录；后续协作以当前 FirstAgent 代码及统一契约为准。
