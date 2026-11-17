# HANDOFF_S1_2 — 结局权威性修复（工作包A评审 R1，S1 第2步）

日期：2026-11-17。状态：**已完成**（新增 test_outcome_authority.py 12 项；全量 208 项全绿）。依据：评审 §2 R1（critical）与 §4.1 修复要求。

## 修复前证据（failing-before）

- 探针复现：`compute_goal_outcome` 对"search 被谎报 optional + open_site ok"返回 **satisfied**（绕过计划）。
- `cmd_finish --goal-outcome` 显式覆盖机器裁决（源码检查确认）。
- `cmd_record` 先落盘后裁决；接受调用方自报 postconditions（与 steps.json 计划契约不比对）。

## 修复内容

| 修复 | 实现 | 对应测试 |
|---|---|---|
| 计划冻结 | prepare 写入 `plan_hash`（steps 数组规范化 SHA256）；record 重新计算比对，篡改即拒绝 | test_plan_tamper_rejected |
| 稳定步骤标识 | `step_id = f"{seq}:{action}"`（build_step 生成）；record 必须携带且在计划内；动作一致性校验 | test_unplanned_step_id_rejected |
| 尝试显式建模 | `attempt` ≥1 且对同 step_id 单调递增；失败→重试→成功按**终局尝试**计一次目标；两次尝试都留痕 | test_attempt_monotonic_rejected / test_retry_terminal_attempt_counts_once |
| 必要性权威=计划 | recorded `required_for_goal` **不再采信**，与计划不符即拒绝（篡改可见） | test_required_for_goal_tamper_rejected / test_required_skipped_blocks_goal（GoalOutcomeTests 改写为计划语义） |
| 后置条件权威=计划 | postconditions 从计划契约取；自报不一致拒绝；observed 逐键、pe 绑定逐键均对计划对账 | test_postconditions_tamper_rejected |
| 机器裁决先于落盘 | `decide` 在 `record_step` 之前执行；`machine_verdict/machine_verdict_reason` 随步持久化；status=ok 而 verdict≠CONTINUE 拒绝落盘 | test_machine_verdict_persisted_with_step |
| 终局保护 | session_end 存在后拒绝 record 与重复 finish | test_duplicate_finalize_rejected / test_post_finalize_record_rejected |
| 注解降级 | `--goal-outcome` → `goal_outcome_annotation`（session_end 新字段，仅记录永不覆盖）；summary 同时展示机器裁决与注解 | test_explicit_goal_override_is_annotation_only |
| 满意路径 | open ok / select_city ok / resolve skipped(非必要) / search ok → satisfied，全步 verdict=CONTINUE | test_satisfied_happy_path_with_machine_verdicts |

## 语义变更声明（破坏性）

- `compute_goal_outcome(steps, planned)`：**必要集合只从 planned 推导**（planned 的键=动作名，值含 required_for_goal）；recorded 自报的 required_for_goal 被忽略。旧契约（requiredness 取自记录步骤）正是 R1 的绕过路径，已废除。
- 无计划的调用（planned=None）→ partial（历史只读口径：run5 重算=partial 不变）。
- `record` 在有 steps.json 的会话中强制 step_id/attempt/计划对账；无计划文件直接拒绝记录。

## 测试

- `test_outcome_authority.py` 12 项（评审验收①④⑤全覆盖 + 篡改/计划篡改/终局保护/满意路径）。
- `test_work_package_a.GoalOutcomeTests` 改写为计划语义（4 项更新 + run5 partial 保留）。
- 全量回归 **208 项全绿**（196 → +12）。

## 边界与遗留

- 历史 run.jsonl（run1–run5）无 step_id/attempt/machine_verdict 字段——只读保留，不回填（评审 §10"旧记录缺字段标 unknown，不补造"）。
- attempt 只做会话内单调，不做全局去重（同 step_id 跨会话各自计）。
- 下一步：S1.3 发布门禁 fail-open 闭合（R3）——双 Schema、证据元数据必填、硬失败优先。

## 八字段日志

2026-11-17 已追加 `pilot_C_phase_S1_2_outcome_authority`；详见 development_log.jsonl 尾部。
