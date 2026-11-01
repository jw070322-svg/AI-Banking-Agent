# 06 · Risk & Compliance 模块

> 目标：让每一笔 Agent 操作都经过**确定性策略检查、服务端预览、一次性确认、提交前重校验**，并留下可解析的 8 字段 Action Log。
> 实现位置：`bank_agent/risk/`。本模块不依赖 LLM，用户文本永远不能直接降低风险等级或跳过审批。

## 1. 模块结构

| 文件 | 职责 |
|---|---|
| `risk/models.py` | 风险等级、策略结果、预览、审批、评估结论 |
| `risk/policy.py` | 确定性、可版本化的策略引擎（限额、余额、白名单、账户状态） |
| `risk/preview.py` | `preview_hash`、过期时间、一次性审批、提交前比对；可选持久化 + 文件锁 |
| `risk/auth.py` | R4 step-up 断言接口与 Demo 实现（强制校验、一次性消费） |
| `risk/compliance.py` | 提示注入识别、不可信内容扫描、PII 检测、日志/回复脱敏 |
| `risk/controls.py` | 合规控制矩阵：义务 → 控制 → 证据 → 审核状态 |
| `risk/action_log.py` | 8 字段 `.md` Action Log 写入 + 应急 JSONL 通道 |
| `risk/engine.py` | 把上述组件接入计划执行：评估 → 确认 → 授权提交 → 写日志 |

## 2. 风险控制流程

```text
用户输入
  → 合规扫描（提示注入 / PII）
  → 意图识别 / 规划 / 工具选择（scope 校验）
  → 风险评估（按注册表 R0–R4；未注册工具默认拒绝）
      ├─ R1/R2：只读，直接执行
      └─ R3/R4：策略检查 → 服务端预览 + preview_hash
  → 用户确认（绑定 preview_hash + user + session）
      └─ R4：step-up 断言校验 + 一次性消费（Demo 实现）
  → 提交前重新校验（余额 / 限额 / 账户 / 收款人 / 策略版本 / scope）
  → 一次性消费确认 → 执行 mutation → 结果校验
  → Action Log（预览 / 确认 / 提交 / 拒绝 / 未执行）
```

任何策略检查异常按 **fail closed** 处理；任何预览/确认/step-up 失效都在资金变动前停止。
未知工具、缺失 scope、缺失评估/预览都会明确拒绝，不存在“回退 R1 放行”。

## 3. 风险分级

| 等级 | 含义 | 本原型中的工具 | 确认 | 认证 |
|---|---|---|---|---|
| R0 | 公共/元信息 | 内部审计写入 | 无 | 无 |
| R1 | 个人只读 | 余额、流水、卡状态、贷款查询 | 无 | 已登录 |
| R2 | 敏感只读/建议 | 当前原型暂未注册 | 无 | 已登录 |
| R3 | 可逆/低风险变更 | `check_transfer_limits`（预览）、`freeze_card` | 预览 + 确认 | 强登录 |
| R4 | 高风险资金变动 | `transfer_funds` | 预览 + 确认 + 逐步认证 + 重校验 | 强认证 + step-up |

风险等级写在 `ToolSpec.risk_tier`，运行时由注册表读取，计划和 LLM 不能覆盖。注册表还会拒绝非法配置：变更类工具低于 R3、R4 未声明 `requires_step_up`、未声明 scope 或声明未知 scope。

`Session.scopes` 由认证/授权服务下发；工具声明所需 scope，选择器、风险评估和提交前授权都会检查。缺少 scope 直接拒绝，不进入执行。

## 4. 策略引擎

`PolicyEngine.check(operation, user_id, params, session)` 返回逐项结果：

- 转账：`amount_positive`、`currency_supported`、`auth_level_strong`、`account_owner`、`account_active`、`account_supports_debit`、`beneficiary_unique`、`beneficiary_owner`、`beneficiary_whitelist`、`single_limit`、`daily_limit`、`balance_sufficient`；
- 卡片冻结：`auth_level_strong`、`card_owner`、`card_status_valid`、`preview_stale`；
- 风险标记：`large_amount_reminder`、`new_beneficiary`、`beneficiary_not_whitelisted`、`card_already_frozen`。

策略参数集中在 [bank_agent/policy_config.json](../bank_agent/policy_config.json)，加载时校验并计算 `policy_config_hash`（SHA-256）。每次检查生成 `policy_check_id`、`policy_version`（当前 `pol_2026_10_20`）和 `policy_config_hash`；检查结果写入 Action Log 的 `risk_check` 字段。这样配置变更、版本和证据可以一一对应。

## 5. 预览与一次性审批

预览哈希：

```text
preview_hash = "sha256:" + SHA-256(canonical_json({
  user_id, operation, from_account_id, beneficiary_id, beneficiary_name,
  amount, currency, fee, balance_snapshot, policy_version, expires_at
}))
```

规则：

- 预览默认 300 秒过期；
- 用户确认生成 `approval_id + confirmation_id`，绑定同一 `preview_hash`、`user_id`、`session_id`；
- 确认只能消费一次，`used_at` 写入日志；
- 提交前重新读取账户/收款人/限额，并重建绑定与预览比对；
- 参数变化 → `PREVIEW_STALE`；过期 → `PREVIEW_EXPIRED`；策略版本变化 → `POLICY_CHANGED`；确认缺失/复用 → `APPROVAL_REQUIRED` / `APPROVAL_INVALID`；
- 以上错误均为受控拒绝，状态为 `rejected`，不会发生资金变动。

### 5.1 持久化与原子消费

传入 `state_path` 时，预览/审批状态会落盘：

- 写入采用临时文件 + `fsync` + `os.replace`；
- 读改写全程持有 `fcntl.flock` 文件锁（Windows 退化为线程锁）；
- 多个线程/进程共享同一 `state_path` 时，只有一个能完成 `authorize_commit`；
- 已提供 `test_concurrent_authorization_only_one_wins` 与 `test_preview_state_survives_reload_and_stays_used`。

仍需诚实说明：**审批消费与账户扣款仍是两个写入点**。生产环境必须把二者放进同一数据库事务/Outbox，并用唯一约束和行锁保证。

### 5.2 R4 step-up 强制门槛

R4 的确认由 `StepUpAuthenticator` 签发一次性断言，断言绑定 `user_id + session_id + preview_hash`，提交前必须 `verify + consume` 成功。缺少断言、伪造 `chat_confirmation`、断言复用都会返回 `AUTH_INSUFFICIENT`，不会执行资金变动。

> Demo 限制：`DemoStepUpAuthenticator` 是进程内模拟，日志明确标记 `step_up_simulated=true`。生产环境必须替换为真实 OTP/生物识别断言服务。

## 6. 合规控制

### 6.1 提示注入

确定性正则识别中英文的“忽略/绕过限额、审批、风控”模式，以及 `system prompt`、`developer mode`、`jailbreak` 等模式。

- 只读请求：记录风险标记，继续执行；
- 涉及 R3/R4 变更：直接阻断，状态 `rejected`，`requires_review=true`；
- 不把用户文本送进 LLM 判断，避免被同一段文本影响；
- 中文模式先去除空白再匹配，覆盖“忽 略 限 额”这类规避写法；
- 代码围栏（```...```）按示例处理，不作为用户指令，降低误报；
- `scan_untrusted_content()` 用于扫描工具输出/RAG 文档；结果只做标记和审计，不能触发新的工具调用；
- 工具输出中的注入模式会写入 `risk_check.untrusted_content_findings`，并标记人工复核；回复仍由固定模板从结构化字段生成，不执行自由文本；
- 系统不使用 `eval` / `exec` / 动态导入处理用户或工具文本；不可信内容始终只作为数据。

### 6.2 PII 与脱敏

写入日志、回复用户前统一脱敏：

| 类型 | 处理 |
|---|---|
| 身份证号 | 全量掩码 `******` |
| 16–19 位卡号/账号 | 仅保留后 4 位 |
| 手机号 | 前 3 + 后 4 |
| 邮箱 | `***@***` |
| 验证码 / OTP | `[REDACTED_OTP]` |
| 敏感字段（token、password、card_number 等） | `[REDACTED]` |

写入 Action Log 前还会二次扫描；发现残留 PII 或敏感键时拒绝写入并记录 `action_log_write_failed` 审计事件。

完整泄漏面覆盖：

- 用户输入文本（含 `trace` 和 `session.history`）；
- 工具返回的嵌套数据（`TraceEvent.detail`）；
- `bank.audit_log`（通过 `audit_redactor` 在写入前统一脱敏）；
- Action Log 与应急 JSONL 通道；
- 完整户名在日志/审计/历史中掩码为“张*”，业务回复仍可对已认证用户显示其收款人姓名。

### 6.3 合规控制矩阵

`risk/controls.py` 定义 8 项控制（RC-01 ~ RC-08），每项包含义务、控制、证据字段、owner、审核状态、证据有效期。每条 Action Log 的 `risk_check.controls[]` 附带 `evidence_hash`，便于逐条复核。详见 [07-compliance-control-matrix.md](07-compliance-control-matrix.md)。

审核状态明确区分 `implemented`、`implemented_demo`、`pending_upstream`，不会把 Demo 级控制说成生产合规。

## 7. Action Log

严格遵循 [05-action-log-spec.md](05-action-log-spec.md)：

- 每个 `.md` 文件只包含一个 8 字段 JSON 对象；
- 顶层字段固定为 `user_id / intent / tool / input / output / risk_check / approval / timestamp`；
- 所有值均为字符串，`input/output/risk_check/approval` 内是 JSON 字符串；
- 文件路径：`logs/YYYYMMDD/HHMMSS-intent-tool-xxxx.md`；
- 不覆盖历史文件；文件名冲突时追加序号；
- 每条 mutation 日志的 `risk_check.controls[]` 带合规控制证据索引；
- 预览已生成但 mutation 未执行（前置步骤失败/策略拒绝）时，记录 `mutation_executed=false`、`passed=false`，不会伪装成 `read_only_turn=pass`；
- 日志写入失败时追加到 `logs/action_log_fallback.jsonl`（仍是 8 字段对象，`fsync`），同时写 `action_log_write_failed` 审计告警，不回滚已提交的业务事务。

典型一组日志：

```text
logs/20261020/111135-transfer.create-transfer.preview-1.0.0-3b8a70.md
logs/20261020/111135-transfer.create-orchestrator.confirmation-1.0.0-54b0a4.md
logs/20261020/111135-transfer.create-transfer_funds-1.0.0-f2c295.md
```

R1/R2 查询按 turn 汇总一条 `orchestrator.turn@1.0.0` 日志；R3/R4 操作分别记录 preview、confirmation、commit；策略拒绝与注入拦截也会写日志。

## 8. 与流水线的接入点

| 位置 | 行为 |
|---|---|
| `orchestrator.handle` 入口 | 合规扫描，写入 `compliance` trace |
| 工具选择 | `Session.scopes` 与 `ToolSpec.scopes` 比对，缺权限拒绝 |
| 工具选择之后 | `RiskComplianceEngine.assess` 生成风险结论与预览；未注册工具默认拒绝 |
| 执行暂停 | `PendingAction.risk_state` 保存评估结果 |
| 用户确认 | 生成一次性审批；R4 强制 step-up 断言，写确认日志 |
| mutation 执行前 | `authorize_step` 重校验 scope/策略/step-up/预览并消费审批 |
| `_finalize` | 脱敏回复、trace、history、audit，并写 Action Log |

新增 trace 阶段：`compliance`、`risk_check`、`approval`。

## 9. 测试覆盖

`tests/test_risk_compliance.py` 共 32 个用例，覆盖：

**策略与预览（10）**：策略版本/检查项、同名收款人歧义、超限 fail closed、R4 预览、卡片冻结 R3、篡改金额 → `PREVIEW_STALE`、过期 → `PREVIEW_EXPIRED`、策略版本变化 → `POLICY_CHANGED`、一次性审批、预览哈希不匹配。

**默认拒绝 / scope / step-up（5）**：未注册工具默认拒绝、缺失 scope 在执行前拒绝、缺少评估/预览时 `authorize_step` 明确抛错而非返回 None、伪造 R4 确认（无 step-up）→ `AUTH_INSUFFICIENT`、step-up 断言一次性消费。

**持久化 / 并发（3）**：state 文件重载后审批仍可用且只能使用一次、两个 store 并发提交只有一个成功、持久化引擎提交日志中的 `used_at/step_up_verified` 准确。

**合规 / 注入 / PII（8）**：提示注入阻断、英文注入识别、代码围栏不误报、空白规避仍识别、PII 日志脱敏、trace/audit 不泄漏 PII、history/trace 不泄漏完整户名、工具输出注入只标记不执行。

**日志准确性 / 应急（3）**：mutation 未执行不再记成 read-only pass、主日志失败写应急 JSONL、只读 turn 汇总日志。

**Action Log / 控制矩阵（3）**：严格 8 字段/全字符串/带时区时间戳、完整 preview/confirmation/commit、控制矩阵覆盖文档。

运行：

```bash
python3 -m unittest discover -s tests -v
```

## 10. 尚未实现 / 生产化清单

- 预览/审批默认仍是内存存储；传入 `state_path` 可持久化并支持本地文件锁，但生产必须落表并使用数据库唯一约束/行锁/事务；
- 审批消费与账户扣款尚未处于同一数据库事务，生产需要 Outbox/事务保证；
- step-up 认证是 `DemoStepUpAuthenticator` 模拟断言，未接入真实 OTP/生物识别服务；
- 未实现数据库事务、双重记账、不可变回执与分布式幂等；
- 文件锁只适用于本地文件系统，不适用于多主机共享存储；
- 未实现策略版本热更新与审批配置后台；
- Action Log 未接入 WORM/哈希链存储；
- 合规控制矩阵的 `review_status` 不代表法务/合规正式签核；
- PII 识别基于正则，无法穷尽所有格式或业务字段；仍需数据分类分级、人工审核和上游系统脱敏；
- R2 工具（模拟、RAG）尚未注册；
- 多动作批量确认、部分成功/未知状态仍未实现。

## 11. 包结构与依赖

`bank_agent/risk/` 是 `bank_agent` 包的一部分，必须通过 `bank_agent.risk` 导入，不能把 `risk/` 当作独立顶层包复制运行。依赖关系：

- `risk/models.py`、`risk/policy.py`、`risk/preview.py`、`risk/engine.py` → `bank_agent.models`（`ToolSpec` / `Session` / `Check` / `ToolError`）、`bank_agent.data`（`POLICY` / `MockBank`）、`bank_agent.utils`；
- `orchestrator.py` → `risk.engine`；
- `stages/execution.py` → `risk.models.RiskControlError`；
- `tools.py` → `bank_agent.models` 的 `ALLOWED_SCOPES` 与 `ToolSpec`；
- 完整文件清单与 SHA-256 见交付报告，`python3 scripts/verify_delivery.py` 会检查这些文件并运行测试。

## 12. 交付复现

```bash
python3 scripts/verify_delivery.py
```

脚本会：

1. 检查必需文件是否存在；
2. 运行 42 个测试；
3. 在临时目录跑一笔转账，校验 Action Log 的 8 字段、时区与 PII 脱敏；
4. 生成源码/测试/文档的 SHA-256 manifest；
5. 写入 `logs/delivery-verification-*.md`。

这只是可复现的交付证据，不是生产合规认证。
