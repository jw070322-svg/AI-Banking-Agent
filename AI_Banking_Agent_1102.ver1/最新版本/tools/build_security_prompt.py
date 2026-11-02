"""Build matching JSON for the reviewed security system prompt; no runtime changes."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'security_design'
SOURCE = ROOT.parent / 'RIsk_evaluation'
MD = OUT / 'banking_llama_security_system.md'
JSON = OUT / 'banking_llama_security_system.json'


def section(text, marker):
    start = text.index(marker)
    next_section = re.search(r'^## ', text[start + len(marker):], re.M)
    return text[start:] if not next_section else text[start:start + len(marker) + next_section.start()]


def numbered_blocks(text, prefix):
    matches = list(re.finditer(r'^### (' + prefix + r'\d{2}) ([^\n]+)\n', text, re.M))
    result = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        result.append({'step': i + 1, 'id': match[1], 'title': match[2],
                       'content': text[match.end():end].strip()})
    return result


def build():
    prompt = MD.read_text(encoding='utf-8')
    reasoning = numbered_blocks(section(prompt, '## 1. '), 'R')
    controls = numbered_blocks(section(prompt, '## 3. '), 'C')
    question_domains = ['年龄', '年收入金额', '主要收入来源', '资产负债状况', '家庭可支配年收入',
                        '家庭收入用于金融投资比例', '投资知识', '投资经验年数', '投资期限', '投资目的',
                        '两种风险收益配置情景', '引起明显焦虑的损失幅度', '收益预期与风险偏好']
    image_numbers = list(range(977, 988)) + [989, 988]
    questions = []
    for i, (domain, number) in enumerate(zip(question_domains, image_numbers), 1):
        matches = list(SOURCE.glob(f'*_{number}_1.png'))
        if len(matches) != 1:
            raise ValueError(f'Expected one screenshot for Q{i:02}: {number}')
        path = matches[0]
        questions.append({'question_id': f'Q{i:02}', 'domain': domain, 'source_file': path.name,
                          'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                          'selected_answer_imported': False, 'approved_wording': None,
                          'option_scores': None, 'status': 'institution_review_required'})

    steps = []
    for match in re.finditer(r'^\d+\. \*\*(S\d{2}) ([^*]+)\*\*：(.+)$', section(prompt, '## 5. '), re.M):
        steps.append({'step': len(steps) + 1, 'id': match[1], 'title': match[2],
                      'required_work_and_evidence': match[3], 'status': 'proposed'})
    acceptance = []
    for match in re.finditer(r'^\| (A\d{2}) \| (.*?) \| (.*?) \|$', section(prompt, '## 6. '), re.M):
        acceptance.append({'id': match[1], 'scenario': match[2], 'pass_condition': match[3],
                           'status': 'not_run', 'evidence_ref': None})
    sources = [{'title': m[1], 'url': m[2], 'checked_date': '2026-10-27'}
               for m in re.finditer(r'^- \[([^\]]+)\]\((https://[^)]+)\)', section(prompt, '## 7. '), re.M)]
    interfaces = []
    for m in re.finditer(r'^\| (GET|PUT|POST) `([^`]+)` \| ([^|]+) \| ([^|]+) \|$', section(prompt, '## 4. '), re.M):
        interfaces.append({'method': m[1], 'path': m[2], 'principal_boundary': m[3].strip(),
                           'contract': m[4].strip(), 'status': 'proposed'})

    artifact = {
        'artifact_type': 'system_prompt_and_security_design_contract',
        'version': '1.0', 'date': '2026-10-27', 'language': 'zh-CN',
        'status': 'design_only_not_deployed',
        'section_order': ['scope_and_facts', 'reasoning', 'open_questions', 'recommendations',
                          'interfaces', 'implementation_steps', 'acceptance', 'sources'],
        'scope_and_facts': {
            'application_path': str(ROOT), 'questionnaire_source_path': str(SOURCE),
            'inference_engine': 'llama.cpp b11900',
            'actual_model': 'Qwen2.5-0.5B-Instruct Q4_K_M',
            'meta_llama_weights_deployed': False,
            'observed_model_url': 'http://127.0.0.1:8794',
            'questionnaire_source_type': '13_screenshots_only',
            'questionnaire_page_implemented_by_this_delivery': False,
            'scoring_rules_available': False,
            'paid_api_allowed': False, 'cloud_fallback_allowed': False,
            'current_gaps': ['model_service_authentication', 'dedicated_service_identity',
                             'verified_os_network_egress_isolation', 'approved_questionnaire_rules',
                             'production_identity_and_object_authorization'],
            'existing_profile_fields_are': 'demo_unverified_not_assessed_profile'
        },
        'reasoning_policy': {
            'type': 'public_auditable_risk_analysis_not_private_chain_of_thought',
            'required_sequence': ['fact_or_assumption', 'risk_scenario', 'control_rationale',
                                  'residual_risk_and_verification'],
            'reasoning_before_recommendations': True,
            'never_claim_unexecuted_tests_passed': True
        },
        'reasoning': reasoning,
        'open_questions': {
            name: None for name in sorted(set(re.findall(r'<([A-Z][A-Z0-9_]+)>', prompt)))
        },
        'recommendations': {
            'status': 'proposed_requires_implementation_and_evidence',
            'architecture': {
                'initiation': 'authenticated_bank_gateway_to_isolated_inference_only',
                'responses': 'permitted_only_on_bank_initiated_connection',
                'physical_data_diode_claim': False,
                'model_network_new_connections': 'deny_by_platform_policy_including_loopback_and_ipv6',
                'model_bank_api_database_files_access': 'deny',
                'external_search': 'separate_broker_inaccessible_to_inference_identity',
                'llm_output': 'untrusted_data_no_execution_no_automatic_followup_calls'
            },
            'inference_interface': {
                'additional_request_properties': False,
                'allowed_routes': [{'method': 'POST', 'path': '/v1/chat/completions', 'caller': 'bank_gateway'},
                                   {'method': 'GET', 'path': '/v1/models', 'caller': 'restricted_health_probe'}],
                'request_allowed_fields': ['model', 'messages', 'stream', 'temperature', 'max_tokens'],
                'server_fixed_fields': ['model', 'system_template', 'stream'],
                'stream': False,
                'forbidden_capabilities': ['tools', 'functions', 'MCP', 'agent_mode', 'callbacks',
                                           'remote_media', 'shell', 'browser', 'arbitrary_URL_fetch'],
                'suggested_initial_limits': {'user_characters': 300, 'body_bytes': 16384,
                                             'output_tokens': 400, 'concurrency': 1, 'timeout_seconds': 45},
                'limits_require_capacity_test': True,
                'suggested_engine_flags': ['--no-agent', '--no-webui', '--no-slots', '--no-cache-prompt',
                                           '--api-key-file <protected-file>'],
                'configuration_deployed': False,
                'health_endpoint_may_bypass_engine_api_key': True,
                'cors_is_authentication': False,
                'response_gate': ['strict_schema', 'size_limit', 'finish_state', 'reject_tool_calls',
                                  'escape_text', 'source_verification', 'needs_evidence_when_ungrounded']
            },
            'access_control': {
                'customer': 'own_subject_only_no_client_scores',
                'suitability_reviewer': 'strong_auth_assigned_case_purpose_and_review_policy',
                'security_evaluator': 'synthetic_environment_no_default_production_access',
                'policy_author_and_approver': 'separate_identities_versioned_release',
                'model_service': 'gateway_requests_only_no_bank_privileges',
                'operations_and_auditor': 'separate_scopes_no_implicit_questionnaire_plaintext',
                'per_request_checks': ['trusted_identity', 'tenant', 'object_owner_or_assignment',
                                       'purpose', 'active_permission', 'version_and_state']
            },
            'information_protection': {
                'raw_customer_answers_to_model': False, 'raw_answers_to_public_search': False,
                'raw_answers_in_browser_localstorage_or_urls': False,
                'raw_prompts_answers_or_secrets_in_audit': False,
                'model_training_with_production_data_by_default': False,
                'personalized_context': 'only_approved_minimized_fields_after_purpose_and_reidentification_review',
                'cross_session_cache_isolation_requires_test': True,
                'controls': ['classification', 'lawful_purpose', 'data_minimization', 'TLS_when_cross_host',
                             'encryption_at_rest', 'separate_key_access', 'backup_and_dump_protection',
                             'no_store_responses', 'approved_retention_and_deletion']
            },
            'risk_questionnaire_integration': {
                'purpose': 'customer_investment_suitability_not_AI_security_scoring',
                'source_manifest': questions,
                'score': None, 'risk_level': None, 'valid_until': None,
                'scoring_status': 'rules_pending',
                'missing_rules_behavior': 'draft_or_needs_review_never_valid_assessment',
                'submission_without_rules': {'http_status': 409, 'code': 'rules_pending'},
                'llm_grading_allowed': False,
                'screenshot_selected_answers_as_defaults': False,
                'institution_review_required': ['Q01_age_65_wording', 'Q02_boundary_30',
                    'Q05_income_title_vs_asset_and_debt_description', 'Q06_Q08_Q09_Q12_interval_boundaries',
                    'Q13_reverse_option_risk_order', 'Q11_hypothetical_returns_not_product_claims'],
                'server_validation': ['approved_version', 'exactly_13_distinct_questions',
                    'one_known_option_per_question', 'no_client_actor_score_risk_level_ruleset',
                    'session_bound_subject', 'idempotency', 'optimistic_version_check'],
                'receipt_fields': ['assessment_id', 'subject_ref', 'questionnaire_version', 'ruleset_version',
                    'assessed_profile_version', 'status', 'assessed_at', 'valid_until'],
                'recommendation_gate': 'current_server_verified_assessed_profile_plus_product_and_liquidity_rules',
                'expired_or_changed_assessment': 'invalidate_relevant_pending_financial_previews',
                'unassessed_basic_education_and_balance_queries': 'remain_available',
                'manual_demo_risk_fields': 'segregate_from_assessed_profile_remove_production_customer_override'
            },
            'audit': {
                'exact_top_level_fields': ['user_id', 'intent', 'tool', 'input', 'output', 'risk_check',
                                           'approval', 'timestamp'],
                'extended_metadata_location': 'nested_objects_only',
                'private_chain_of_thought': 'never_record',
                'low_entropy_answers_hashing': 'not_a_substitute_for_redaction',
                'production_append_only_integrity_and_access_separation': 'required_not_proven_by_local_jsonl'
            },
            'detailed_controls': controls
        },
        'interfaces': interfaces,
        'implementation_steps': steps,
        'acceptance': acceptance,
        'sources': sources,
        'system_prompt': prompt
    }
    JSON.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    parsed = json.loads(JSON.read_text(encoding='utf-8'))
    assert parsed['system_prompt'] == prompt
    assert list(parsed).index('reasoning') < list(parsed).index('recommendations')
    assert [r['id'] for r in reasoning] == [f'R{i:02}' for i in range(1, 9)]
    assert [c['id'] for c in controls] == [f'C{i:02}' for i in range(1, 11)]
    assert [s['id'] for s in steps] == [f'S{i:02}' for i in range(1, 8)]
    assert [a['id'] for a in acceptance] == [f'A{i:02}' for i in range(1, 13)]
    assert len(questions) == 13 and len(interfaces) == 6 and len(sources) == 7
    report = {'artifact_status': 'design_only_not_deployed', 'validation_passed': True,
              'markdown_json_prompt_equal': True, 'reasoning_precedes_recommendations': True,
              'risk_count': len(reasoning), 'control_count': len(controls), 'question_count': len(questions),
              'proposed_interface_count': len(interfaces), 'implementation_step_count': len(steps),
              'planned_acceptance_count': len(acceptance), 'security_acceptance_executed': False,
              'markdown_sha256': hashlib.sha256(MD.read_bytes()).hexdigest(),
              'json_sha256': hashlib.sha256(JSON.read_bytes()).hexdigest()}
    (ROOT / 'reports/security-prompt-validation.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    build()
