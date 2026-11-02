# Agent Action · Risk & Compliance review remediation

```json
{
  "user_id": "team:risk-compliance",
  "intent": "remediate_risk_compliance_review",
  "tool": "code.remediate@1.0.0",
  "input": "{\"review_items\":[\"policy_governance\",\"default_deny_and_scopes\",\"preview_persistence_atomicity\",\"r4_step_up_gate\",\"compliance_control_matrix\",\"prompt_injection_hardening\",\"pii_leak_paths\",\"log_accuracy_and_fallback\",\"dependency_manifest\",\"reproducible_delivery\"],\"constraints\":[\"no_real_funds\",\"fail_closed\",\"8_field_logs\",\"honest_limitations\"]}",
  "output": "{\"status\":\"completed\",\"fixed\":{\"policy_governance\":\"bank_agent/policy_config.json + policy_config_hash + docs/07 control matrix\",\"default_deny_scopes\":\"unknown tools denied; Session.scopes vs ToolSpec.scopes checked in selection/assess/authorize; authorize_step raises instead of returning None\",\"preview_persistence_atomicity\":\"PreviewStore state_path + fsync + os.replace + fcntl lock; concurrent single-consumer test; DB transaction still pending\",\"r4_step_up\":\"StepUpAuthenticator hard gate: forged chat confirmation and assertion reuse -> AUTH_INSUFFICIENT\",\"compliance_evidence\":\"RC-01..RC-08 controls with evidence_hash/review_status in every risk_check\",\"injection\":\"code-fence exclusion, whitespace normalization, untrusted tool output scan + flag, malicious input tests\",\"pii\":\"redaction for action logs, fallback, trace, session history, audit log; phone/name leakage tests\",\"log_accuracy\":\"mutation-not-executed logs passed=false + mutation_executed=fail; fallback JSONL + fsync + audit alert\",\"delivery\":\"scripts/verify_delivery.py + SHA-256 manifest + delivery report\"},\"tests\":{\"total\":42,\"passed\":42},\"demo_logs\":15,\"delivery_report\":\"logs/delivery-verification-20261020-193709.md\",\"residual_risks\":[\"local_state_file_not_db_transaction\",\"simulated_step_up_auth\",\"regex_pii_detection_not_exhaustive\",\"compliance_matrix_pending_legal_signoff\"],\"token_usage\":{\"initial_tokens\":15000000,\"remaining_pct_approx\":\"99.9%\",\"threshold_pct\":10,\"stop_triggered\":false}}",
  "risk_check": "{\"mutating\":false,\"real_funds\":false,\"test_side_effects\":\"temp_dirs_and_local_demo_logs_only\",\"pii_paths_reviewed\":[\"action_log\",\"fallback_log\",\"trace\",\"session_history\",\"audit_log\"],\"fail_closed_reviewed\":true,\"default_deny_reviewed\":true}",
  "approval": "{\"required\":false,\"reason\":\"code_docs_tests_only\",\"reviewer\":\"pending_review\",\"decision\":\"not_required\"}",
  "timestamp": "2026-10-20T19:33:57+08:00"
}
```
