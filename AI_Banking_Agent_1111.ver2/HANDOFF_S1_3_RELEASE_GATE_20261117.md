# HANDOFF_S1_3 — 发布门禁 fail-open 闭合（工作包A评审 R3，S1 第3步）

日期：2026-11-17。状态：**已完成**（新增 R3GateClosureTests 9 项；全量 217 项全绿）。依据：评审 §2 R3（critical，"critical before release"）与 §4.2 修复要求。

## 修复前证据（failing-before）

- 评审复现：report 不带 sources/evidence_verified_at → pass（fail-open）。
- 本轮探针复现（2026-11-16/17）：`evaluate_release_gate(report_without_evidence_metadata, policy)` → **pass**。
- 门禁缺口核查：policy 必填清单缺 evidence_freshness_days 语义强制；allowed_sources 仅在字段存在时检查。

## 修复内容

| 修复 | 实现 | 对应测试 |
|---|---|---|
| 策略契约化 | 新增 `schemas/release_policy.schema.json`；策略先过 Schema（缺字段/类型错 → incomplete "策略不符合契约"） | test_policy_without_freshness_config_rejected / test_policy_must_be_configured |
| 报告契约化 | 新增 `schemas/release_report.schema.json`（含 model/template/dataset 哈希格式 pattern、findings 类型枚举、amounts 整数）；报告非法即 incomplete | test_hash_format_incomplete / test_missing_report_field_is_incomplete |
| **证据元数据必填** | 每个适用检查必须携带非空 sources（⊆ allowed）与 evidence_verified_at（合法、非未来、在 evidence_freshness_days 内）——**缺省即 incomplete，不再跳过** | test_failing_before_probe_now_incomplete / test_missing_sources_incomplete / test_missing_evidence_time_incomplete / test_future_evidence_incomplete / test_stale_evidence_incomplete / test_disallowed_source_incomplete |
| 必检清单对账 | report.required_checks 必须与 policy.required_checks 一致（不信任自报） | test_required_checks_mismatch_incomplete |
| 非有限指标 | metrics 拒绝 NaN/Inf（math.isfinite） | test_nonfinite_metric_incomplete |
| 金额非有限 | amounts_cents 加 math.isfinite 守卫 | test_budget_amount_missing_incomplete（fixture 改为负数整数） |
| **硬失败优先** | 隐私外发/错误推荐超预算发现即使报告其他字段不完整（如必检全未执行）也返回 **fail**（不再被 incomplete 掩盖） | test_hard_fail_precedence_over_incomplete_fields / test_override_recommendation_fail_precedence |
| 逐检查失败累积 | 单检查的多项失败（来源+证据时间）一次全报，不首错即停 | test_failing_before_probe_now_incomplete（双原因断言） |

## 接口变更

- `evaluate_release_gate` 前两步改为 Schema 校验（策略/报告）；策略或报告非法 → incomplete，原因含 Schema 错误详情。
- 硬失败（privacy_leak / budget_override_recommendation）在覆盖核验**之前**判定，立即 fail。
- 不适用检查的豁免仍须"理由 + 策略允许"两者齐备（既有语义不变）。
- 既有测试 fixture 全面补齐 sources/evidence_verified_at/hex 哈希——收紧后旧写法（缺元数据、"m/t/d"哈希、未来日期）会被如实拒绝，这正是修复目的。

## 测试

- 新增 `R3GateClosureTests` 9 项（评审 §4.2 验收逐条）。
- 更新 ReleaseGateTests/GateGapTests fixture 至新契约。
- 全量回归 **217 项全绿**（208 → +9）。

## 边界与遗留

- 评审要求"Bind sample IDs/counts to a verified dataset/evidence manifest"——dataset_hash 契约化已做，但"verified dataset manifest"（数据集清单文件+逐样本哈希）属工作包 D 冻结机制，本轮不实现（已在 §11 待办追踪）。
- 下一步：S1.4 城市证据强制（R4）。

## 八字段日志

2026-11-17 已追加 `pilot_C_phase_S1_3_release_gate_fail_open_closure`。
