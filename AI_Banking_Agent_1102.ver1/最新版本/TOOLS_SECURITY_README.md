# 1029 tools calling 与 security 增量交付

## 推理部分：现状、缺口与添加依据

本文件只提供可复核的比较、设计依据和测试证据，不记录私有思维链。

基底是 `F:\AI_Banking\AI_Banking_Agent_1028.ver1`，输入为 `F:\AI_Banking\Teammate_output\eva output\1029`。新版本是 `F:\AI_Banking\AI_Banking_Agent_1029.ver1`。此前 LOCAL_AGENT_HANDOFF.md 原文保留，本轮状态见 HANDOFF_1029_TOOLS_SECURITY.json。

| 已有实现与实际缺口 | 增量处理 | 不改变的边界 |
|---|---|---|
| 13 个工具、参数契约、计算和审计代码已提供；交付文件展平且带 `(1)` 等重名后缀 | 按原文档恢复 `first_agent/vendor/eva/tool_calling/tools/` 与 `security/` 包结构，文件字节不改 | 所有原件和既有应用源文件保留 |
| 原安全模块调用 `scan_input(ignore_code_blocks=...)` 和 `scan_untrusted_content`，旧合规扫描器没有这两个接口形态 | `security/compatibility.py` 提供适配，继续扫描全部内容 | 不跳过旧安全规则，不改 risk/compliance.py |
| 原幂等记录只缓存成功结果，检查与执行分离；并发与异常后的重试可能再次进入处理函数 | `tool_calling/hardening.py` 添加原子 SQLite 预约、同实例串行和未知结果保留，重绑定 `call/invoke` 别名 | 不重写原注册器、处理函数或银行账本 |
| 原安全返回对象同时携带 safe_data 和原始 tool_result.data/evidence | `security/hardening.py` 只返回过滤后的副本；原始 evidence 不进入面向调用者的对象 | 原输出校验器继续生效 |
| 参数默认值在工具层才补齐，确认与执行可能绑定不同形态；已核验的加强验证状态没有传到工具上下文 | 确认前先规范化参数；仅从服务器已消费的一次性确认记录传递加强验证证明 | 模型和客户端不能自报身份、权限或“已确认” |
| 确认记录校验与状态转换跨锁；输出检查或最终审计失败可能发生在操作已经执行之后 | 新子类将确认转换置于同一锁内；执行后异常明确要求核对回执 | 不自动重试写操作，不把未知结果称为未执行 |
| 缺少兼容的模块组装及模型工具调用入口 | `security/runtime.py` 组装同一数据源的注册器/鉴权/授权/确认/输出审查；`tool_calling/model_bridge.py` 接收严格工具调用 JSON | 不执行任意函数、代码、URL或回调；不新增模型、外网或付费调用 |
| 本地代理需要在低额度时留交接 | `security/quota_handoff.py` 接收宿主可信额度快照，任一窗口剩余 ≤15% 时保存 JSON 并抛出暂停信号；未知或过时额度同样暂停 | 不从模型参数猜额度，不把银行客户余额当开发账号额度 |

### 验证顺序与证据

1. 先校验目录、旧交接、宿主额度；记录 SHA-256 基线。
2. 恢复包结构并实际导入：13 个工具全部注册。
3. 走真实 Python 调用链，发现并修复扫描器接口不兼容，再测试正常读写和拒绝路径。
4. 全系统一次回归：201 项后端（166 既有 + 当时35专项）、85 项前端，均通过。
5. 最后增加“执行后输出过滤器异常”防护，并运行当前全部36项专项，均通过；旧模块与前端无新增变动，因此未重复跑旧回归。
6. 逐文件复核618个继承文件和73个交付输入/副本无变化。73个输入包含32个Python源文件、4份说明、5份日志和32个缓存文件；运行时导入恢复后的Python源文件。

报告：`reports/1029-all-selfcheck.json`、`reports/1029-all-selfcheck.txt`、`reports/1029-modules-selfcheck.json`、`reports/1029-modules-selfcheck.txt`、`reports/1029-verification.json`。原历史测试报告保持原样。

## 结论部分：如何合并和调用

### 完整代码交付

- `TOOLS_SECURITY_ADDITIONS.md`：本轮7个新增实现文件的完整文本，逐文件使用【补全内容（板块名、位置）起/止】标记。
- `TOOLS_SECURITY_COMPLETE_CODE.md`：两个相关板块全部39个Python源文件的完整代码，无省略；原32个文件与输入字节一致。
- `tools_security_1029_additive.zip`：可合并源代码包、专项测试与说明。不含模型、密钥、运行数据库、源日志或缓存。
- 不要覆盖旧 `first_agent/security.py`、`first_agent/vendor/security/` 或 `first_agent/vendor/eva/risk/`。本次目标是新建的 `first_agent/vendor/eva/security/` 和 `first_agent/vendor/eva/tool_calling/`。
- 应用端使用新增的 `build_runtime`、`HardenedToolRegistry`、`HardenedToolGateway`；原类仍保持原行为，直接调用原类不会自动获得新增防护。

### 自检

在新版本目录执行：

```powershell
python -X utf8 -m first_agent.vendor.eva.security.selfcheck --scope modules
python -X utf8 -m first_agent.vendor.eva.security.selfcheck --scope all
```

模块自检是36项；全量目前应运行202项后端和85项前端。报告中记录的实际已运行次数以上节为准。测试仅用合成数据，并把旧外部服务调用替换为离线测试返回。

### 兼容调用示例（模拟环境）

```python
from getpass import getpass
from first_agent.vendor.eva.security.runtime import build_runtime
from first_agent.vendor.eva.security.auth import Credentials, UserSeed
from first_agent.vendor.eva.tool_calling.model_bridge import ModelToolBridge

# 本示例创建独立的演示数据源，不代表现有网页的客户账户。
password = getpass('设置本次模块演示密码：')
runtime = build_runtime('runtime/tools-security', users=[
    UserSeed('CUST-001', 'demo', password)
])
login = runtime.auth.authenticate(Credentials('demo', password))
assert login.ok

# token只在服务器保存；不放进模型上下文或日志。
balance = runtime.gateway.execute(login.token, 'get_account_balance', {})
print(balance.to_dict())

# 对模型仅暴露function描述符；返回的工具建议仍必须经过本桥校验。
bridge = ModelToolBridge(runtime.gateway)
tool_schemas = bridge.descriptors(login.token)
model_result = bridge.dispatch(login.token, [
    {'id': 'call_1', 'type': 'function', 'function': {
        'name': 'get_account_balance', 'arguments': '{}'
    }}
])
print(model_result)

# 写操作必须通过用户界面的单独确认动作，不能让模型自动运行此段。
arguments = {'alert_type': 'transaction_above', 'threshold': '100.00'}
preview = runtime.gateway.prepare_confirmation(login.token, 'create_alert', arguments)
assert preview.ok
print(preview.challenge.to_dict())
if input('确认创建以上模拟提醒？输入 yes：') == 'yes':
    approval = runtime.gateway.confirm(login.token, preview.challenge.confirmation_id,
                                       presented_details=preview.challenge.details)
    if approval.ok:
        result = runtime.gateway.execute(login.token, 'create_alert', arguments,
                                          confirmation_id=preview.challenge.confirmation_id)
        print(result.to_dict())
```

### 额度交接

本会话在开发阶段通过宿主额度工具复核实际额度。独立本地代理须给 `QuotaGuard` 注入宿主可信回调；此模块不具备自行读取Codex账号额度的私有接口。回调格式为 `{"observed_at": "带时区ISO时间", "windows": {"primary": 余额百分比, "weekly": 余额百分比}}`，最多允许5分钟旧快照。应在每项新的业务/代码/GitHub写操作之前调用 `check()`，上层收到 `QuotaPaused` 必须停止，不能忽略异常后继续执行。暂停记录含用户ID、剩余额度、操作记录、后续处理建议及时间；未知额度写 null。

沿用根AGENTS的保守边界 ≤15%，覆盖本次“低于15%”要求。恢复需要用户明确继续，且所有可信窗口高于15%。本轮最终实际额度写在 HANDOFF_1029_TOOLS_SECURITY.json。

### 实际接入范围及保留限制

这次完成的是所提供 Module 6/8 的可导入代码、补全防护、组装接口与测试。现有网页、RAG、Wind、产品曲线及原业务路由没有修改；网页原入口不会自动切换到这组新类。原应用继续用 `启动增量RAG.bat`（8799），运行本版前须确保该端口没有被旧版占用。**新模块的独立模拟账户不是网页账本，不能混用，也不能宣称网页请求已经全部经过新网关。** 后续若要求让所有网页请求迁移到新网关，需要单独设计现有会话/授权/唯一账本映射，并保持此轮不动其他板块的范围约束。

默认工具数据、身份提供者和预算/提醒存储仍是原件明确标注的模拟或内存实现；预算提醒不发送短信，也不会后台监测。生产身份认证、共享会话存储、真实加强认证、真实银行交易、生产风险证据接口都没有被虚构接通。R4缺少必要能力时拒绝；完整模拟转账仅在明确启用测试替身的测试中验证。

持久化防重表保存调用摘要与状态，不保存原始参数、密码或响应正文；它不是银行交易账本。重启后不能还原原内存响应，返回需核对回执，且不再次派发。独立的新幂等键/新确认代表新的操作，不提供跨新键的交易意图去重。SQLite预约与外部银行提交并非同一事务，不能宣称实现真实资金交易的“恰好一次”。

规则式注入检测和脱敏不构成完备DLP或生产合规认证；网络出口隔离、部署权限与银行内部审计保留策略仍属于部署层。本轮没有调用付费API、训练模型、外发客户数据或修改GitHub。
