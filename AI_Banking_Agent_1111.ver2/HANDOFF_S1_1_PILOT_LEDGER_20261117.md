# HANDOFF_S1_1 — 试点台账信任修复（工作包A评审 R2，S1 第1步）

日期：2026-11-17。状态：**已完成**（23 项台账测试 + 全量 196 项全绿）。依据：AGENT_REVIEW_AND_CONTINUATION_PLAN_20261116.md §2 R2 与 §5 指派（"从台账默认路径缺陷与结局权威性开始"）。

## 修复前证据（failing-before）

评审复现 + 本轮探针复现（2026-11-16/17）：
1. `pilot_ledger.stats()` 无参调用 → `TypeError: Path(None)` 崩溃（默认 CLI 路径不可用）
2. `start` 接受不存在的 session 路径与虚假 local_real_file 标签
3. `finish` 接受空证据 + 断言 satisfied；哈希仅前缀比较
4. 全部 waiting_user 记为墙阻断；0 运行也产出率值
5. 台账全文件重写无原子性

## 修复内容（pilot_ledger.py 重写为 v2 纪律版）

| 修复 | 实现 | 对应测试 |
|---|---|---|
| 默认路径 | `_ledger_path(None)` → DEFAULT_LEDGER | test_ledger_path_none_returns_default / test_stats_no_arg_does_not_crash |
| 原子持久化 | 临时文件 + `os.replace` | （写路径改造，无遗留 .tmp） |
| 会话必须先创建 | start 要求 session_dir 存在且含 run.jsonl/run_start | test_nonexistent_session_rejected / test_session_without_run_jsonl_rejected |
| 来源绑定 | 必须提供真实来源文件路径；record_id 须唯一可解析；**synthetic/test_only 标记记录即拒绝（调用方 local_real_file 标签不可信）**；city 从来源记录推导，所报不一致即拒绝（防串客）；来源记录指纹入行 | test_missing_source_path_rejected / test_record_not_found_rejected / test_duplicate_record_in_source_rejected / test_synthetic_flagged_record_rejected_despite_label / test_cross_customer_city_mismatch_rejected |
| 结局推导 | finish 从会话 run.jsonl（session_end）**推导** run_outcome/goal_outcome/user_takeover；CLI 断言仅交叉校验、不一致即拒绝 | test_finish_derives_outcomes_from_session / test_inconsistent_cli_assertion_rejected / test_takeover_derived_from_session |
| 会话必须已 finalize | 缺 session_end → 拒绝闭合（先 run_session finish 再试点 finish） | test_unfinalized_session_rejected |
| 证据纪律 | ≥1 条引用；**完整 64 位十六进制 SHA256**（前缀废除）；文件存在+哈希匹配 | test_empty_evidence_rejected / test_prefix_hash_evidence_rejected |
| 墙分类收严 | waiting_user 仅在步骤 error_code/response_summary 命中 FORCE_WALL_KEYWORDS 时计 wall_blocked | test_wall_classification_requires_confirmed_marker |
| 四计数与零运行 | started/open/closed/invalid；closed=0 → `not_evaluated`（不产出率值）；率值附显式分子/分母；非 local_real_file 行单独计数 | test_zero_runs_not_evaluated / test_counts_and_rates_with_numerators / test_invalid_row_reported_not_counted |
| 重复防护 | 同记录同场景同城市未闭合试点拒绝重复登记；重复 finish 拒绝 | test_duplicate_open_pilot_rejected / test_double_finish_rejected / test_finish_unknown_pilot_rejected |

## 接口变更（破坏性收紧，历史台账只读不受影响）

- `start` 新增必参 `source_path`；城市以来源记录为准。
- `finish` 的 `--run-outcome/--goal-outcome/--user-takeover` 从"断言"降为"交叉校验"（可省略，缺省推导）；`--evidence-refs` 必填且须全哈希。
- `stats` 输出新增 `status(not_evaluated/evaluated)`、started/open/closed/invalid、`rate_numerators_denominators`；行结构新增 source_path/source_fingerprint/wall_blocked/finished_at。
- 台账 procedure 变更：**run_session prepare 先于 pilot_ledger start**（会话须先存在）。

## 测试

`test_pilot_ledger.py` 重写：**23 项全部通过**（DefaultPath 2 / Start 9 / Finish 7 / Stats 4 / Verify 3 − 部分合并计数）。全量回归 **196 项全绿**（run_all_checks，2026-11-17）。

## 边界与遗留

- 台账当前为空（无真实试点行）；历史 16 字符前缀证据引用仅在旧会话文件中，只读保留不回填。
- 墙阻断判定依赖步骤 error_code/response_summary 文本命中 FORCE_WALL_KEYWORDS——若平台改文案需更新关键词表（与 executor.base 共用单一来源）。
- 下一步：S1.2 结局权威性（R1）——计划哈希、step_id+attempt、机器裁决先于落盘、`--goal-outcome` 注解降级。

## 八字段日志

2026-11-17 已追加 `pilot_C_phase_S1_1_ledger_trust_repair`（intent 字段）；详见 development_log.jsonl 尾部。
