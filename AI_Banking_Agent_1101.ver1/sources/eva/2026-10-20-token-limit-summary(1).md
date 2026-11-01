# Agent Action · token-limit summary

```json
{
  "user_id": "team:risk-compliance",
  "intent": "summarize_risk_compliance_work_under_token_limit",
  "tool": "summary.write@1.0.0",
  "input": "{\"token_budget\":15000000,\"threshold_pct\":10,\"triggered\":false,\"scope\":\"risk_compliance_build_and_review_remediation\"}",
  "output": "{\"status\":\"completed\",\"tests\":{\"total\":42,\"passed\":42},\"demo_logs\":15,\"delivery_report\":\"logs/delivery-verification-20261020-193709.md\",\"key_changes\":[\"policy_config_hash\",\"default_deny_and_scopes\",\"r4_step_up_hard_gate\",\"preview_state_persistence_and_file_lock\",\"compliance_control_matrix_RC01_RC08\",\"code_fence_and_untrusted_content_scan\",\"trace_audit_history_pii_redaction\",\"mutation_not_executed_log_accuracy\",\"fallback_jsonl_audit_channel\",\"delivery_verification_script_and_manifest\"],\"residual_risks\":[\"local_state_file_not_db_transaction\",\"simulated_step_up_auth\",\"regex_pii_detection_not_exhaustive\",\"compliance_matrix_pending_legal_signoff\"]}",
  "risk_check": "{\"mutating\":false,\"real_funds\":false,\"token_threshold_reached\":false,\"pii_paths_reviewed\":true}",
  "approval": "{\"required\":false,\"reason\":\"summary_only\",\"decision\":\"not_required\"}",
  "timestamp": "2026-10-20T19:36:43+08:00"
}
```
