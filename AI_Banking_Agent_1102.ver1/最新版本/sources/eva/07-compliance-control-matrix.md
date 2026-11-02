# 07 · 合规控制矩阵与证据

> 目的：把“义务 → 控制 → 证据 → 审核状态”变成可机器读取的记录，而不是只在文档里声明“已合规”。
> 代码实现：`bank_agent/risk/controls.py`。每条 Action Log 的 `risk_check.controls[]` 都会带 `control_id`、义务、控制、owner、`review_status`、证据有效期和 `evidence_hash`。

## 1. 控制矩阵

| ID | 义务 | 控制 | 证据字段 | Owner | 审核状态 | 证据有效期 |
|---|---|---|---|---|---|---|
| RC-01 | 资金变动前必须完成确定性策略检查 | `PolicyEngine.check` + fail closed | `policy_version`, `policy_config_hash`, `policy_check_id`, `checks`, `risk_flags` | risk-module | implemented | 1 天 |
| RC-02 | 高风险操作必须使用服务端预览并防止参数篡改 | `PreviewStore` + `preview_hash` + `expires_at` | `preview_id`, `preview_hash`, `expires_at`, `binding` | risk-module | implemented | 1 天 |
| RC-03 | 资金变动必须获得一次性用户确认 | `Approval` + `confirmation_id` + `used_at` | `approval_id`, `confirmation_id`, `decision`, `one_time`, `used_at` | risk-module | implemented | 1 天 |
| RC-04 | R4 操作必须通过 step-up 认证 | `StepUpAuthenticator` 强制断言校验与一次性消费 | `auth_method`, `step_up_verified`, `step_up_simulated` | risk-module | implemented_demo | 1 天 |
| RC-05 | 提示注入与不可信内容不得改变授权或工具参数 | `ComplianceScanner` + 固定模板 + 内容隔离标记 | `findings`, `blocked`, `untrusted_content_findings` | risk-module | implemented | 1 天 |
| RC-06 | 日志与审计记录必须最小化 PII | 统一脱敏 + Action Log 写前二次扫描 | `redaction_applied`, `pii_scan` | risk-module | implemented | 1 天 |
| RC-07 | 关键 Agent Action 必须可追溯 | 8 字段 `.md` + 应急 JSONL | `log_format`, `timestamp`, `audit_id`, `fallback_path` | risk-module | implemented | 30 天 |
| RC-08 | 需要人工复核的异常必须被标记 | `requires_manual_review` + audit 告警 | `requires_manual_review`, `severity` | risk-module | implemented | 30 天 |

## 2. 证据怎么验证

1. 打开对应 Action Log `.md`，解析 8 字段 JSON；
2. 读取 `risk_check.controls[]`；
3. 用 `evidence_hash` 对应的控制项字段重新计算 SHA-256（canonical JSON），应与记录一致；
4. `review_status=implemented_demo` 表示控制已生效，但依赖 Demo 实现（如模拟 step-up），不能声称达到生产合规；
5. `review_status=pending_upstream` 的控制必须由合规/法务/上游服务确认后才能关闭。

## 3. 审核状态说明

| 状态 | 含义 | 是否可对外宣称合规 |
|---|---|---|
| `implemented` | 代码与测试均存在，证据可复现 | 仅限本文档定义的范围 |
| `implemented_demo` | 有强制代码路径，但依赖模拟服务 | 否，必须替换为生产服务并重新审核 |
| `pending_upstream` | 依赖上游义务定义、法务意见或外部系统 | 否 |

## 4. 仍然依赖上游 / 生产化的事项

- step-up 认证是 `DemoStepUpAuthenticator`，生产必须替换成真实 OTP/生物识别断言服务；
- 预览/审批持久化是本地 state 文件 + 文件锁，生产必须换成数据库事务/行锁/唯一约束；
- 审批消费与账户扣款尚未处于同一数据库事务，生产需要 Outbox/事务保证；
- 义务条款、保留期限、跨境/隐私要求需要法务和合规团队确认；
- `evidence_ttl_days` 只是 Demo 级策略，生产保留期限以监管要求为准。

## 5. 与 Action Log 的关系

`risk_check` 仍是 8 字段日志中的一个 JSON 字符串，`controls[]` 只是其中的结构化证据索引。这样既保持与 `docs/05-action-log-spec.md` 的 8 字段约束一致，也避免把控制信息散落到日志顶层。
