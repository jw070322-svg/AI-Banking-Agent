# Agent Action · account.balance.read · orchestrator.turn@1.0.0

```json
{
  "user_id": "CUST-001",
  "intent": "account.balance.read",
  "tool": "orchestrator.turn@1.0.0",
  "input": "{\"message\":\"查一下尾号9999的余额\",\"plan_id\":\"PLAN-E118B5EE2B\",\"tools\":[\"get_account_balance\"]}",
  "output": "{\"status\":\"rejected\",\"audit_id\":\"AUD-A4D90590DF\",\"verification_passed\":true,\"result_count\":1,\"requires_review\":false}",
  "risk_check": "{\"policy_version\":\"pol_2026_10_20\",\"passed\":true,\"outcome\":\"rejected\",\"checks\":{\"read_only_turn\":\"pass\"},\"risk_flags\":[],\"requires_confirmation\":false,\"requires_step_up_auth\":false,\"requires_manual_review\":false,\"untrusted_content_findings\":[],\"controls\":[{\"control_id\":\"RC-05\",\"obligation\":\"提示注入与不可信内容不得改变授权或工具参数\",\"control\":\"ComplianceScanner + 固定模板 + 内容隔离标记\",\"owner\":\"risk-module\",\"review_status\":\"implemented\",\"evidence_ttl_days\":1,\"evidence_fields\":[\"findings\",\"blocked\",\"untrusted_content_findings\"],\"evidence_hash\":\"sha256:440d4af1ff86578fb7e6e1fa1a0c505de014735075853b7d85440ef6fb6dfc30\"},{\"control_id\":\"RC-06\",\"obligation\":\"日志与审计记录必须最小化 PII\",\"control\":\"ComplianceScanner.redact + ActionLogWriter 写前二次扫描\",\"owner\":\"risk-module\",\"review_status\":\"implemented\",\"evidence_ttl_days\":1,\"evidence_fields\":[\"redaction_applied\",\"pii_scan\"],\"evidence_hash\":\"sha256:4aa6638e8a9be7829b930c80d1316e1d8f551cfc10756675e95ce2380316503b\"},{\"control_id\":\"RC-07\",\"obligation\":\"关键 Agent Action 必须可追溯\",\"control\":\"8 字段 .md Action Log + 应急 JSONL 通道\",\"owner\":\"risk-module\",\"review_status\":\"implemented\",\"evidence_ttl_days\":30,\"evidence_fields\":[\"log_format\",\"timestamp\",\"audit_id\",\"fallback_path\"],\"evidence_hash\":\"sha256:008faeb28fe2e8cca23b7282d9f60188cd059d880449ddc54c8ad8ceb0767f0d\"},{\"control_id\":\"RC-08\",\"obligation\":\"需要人工复核的异常必须被标记\",\"control\":\"requires_manual_review + audit 告警\",\"owner\":\"risk-module\",\"review_status\":\"implemented\",\"evidence_ttl_days\":30,\"evidence_fields\":[\"requires_manual_review\",\"severity\"],\"evidence_hash\":\"sha256:1e2926409ffef9cb4cfc45dfaf0226faabd3ba2765679085659b78370f962297\"}]}",
  "approval": "{\"required\":false,\"decision\":\"not_required\"}",
  "timestamp": "2026-10-20T19:36:00+08:00"
}
```
