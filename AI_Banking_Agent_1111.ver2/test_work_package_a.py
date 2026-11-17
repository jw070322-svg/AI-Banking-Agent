"""工作包A测试（设计文档 §4）：动作来源/方法/跳过原因/目标绑定、run_outcome 与
goal_outcome 分离、三态发布门禁。历史口径纠正：completed 不等于目标满足。"""
import json
import tempfile
import unittest
from pathlib import Path

from evaluation.gates import evaluate_release_gate
from executor.base import (STATUS_FAILED, STATUS_OK, STATUS_SKIPPED,
                           STATUS_WAITING_USER, ExecutionLog, evidence_ref_for,
                           new_session_dir)
from executor.run_session import cmd_finish, compute_goal_outcome
from schema_check import load_schema, validate
from workflow import build_plan


def customer():
    return {"city": "杭州", "special_event": "生日",
            "budget": {"max": "600", "currency": "CNY", "basis": "total"}, "party_size": 4}


def evidence(session, name="shot.png"):
    path = session / "evidence" / name
    path.write_bytes(b"evidence-bytes")
    ref = evidence_ref_for(session, path)
    return ref.split("#")[0], ref.split("#sha256:", 1)[1]


class ActionMetadataTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.session = new_session_dir(self._temp.name)
        self.log = ExecutionLog(self.session)
        self.log.run_start("synthetic")

    def tearDown(self):
        self._temp.cleanup()

    def _ok_step(self, seq=1, action="search"):
        rel, sha = evidence(self.session)
        return self.log.record_step(
            seq=seq, action=action, params={}, started_at="t0", ended_at="t1",
            duration_ms=100, status=STATUS_OK, evidence_ref=f"{rel}#sha256:{sha}",
            action_source="automation", execution_method="direct_navigation",
            required_for_goal=True,
            postcondition_evidence=[{"key": "keyword_echo", "evidence_ref": rel,
                                     "sha256": sha, "verified_at": "t1",
                                     "run_id": self.log.load_lines()[0]["run_id"]}])

    def test_new_fields_recorded(self):
        record = self._ok_step()
        self.assertEqual(record["action_source"], "automation")
        self.assertEqual(record["execution_method"], "direct_navigation")
        self.assertTrue(record["required_for_goal"])
        self.assertEqual(record["postcondition_evidence"][0]["key"], "keyword_echo")

    def test_skipped_without_skip_reason_rejected(self):
        with self.assertRaises(ValueError):
            self.log.record_step(seq=2, action="resolve_location", params={},
                                 started_at=None, ended_at=None, duration_ms=0,
                                 status=STATUS_SKIPPED)

    def test_skipped_with_reason_and_not_required(self):
        record = self.log.record_step(
            seq=2, action="resolve_location", params={},
            started_at=None, ended_at=None, duration_ms=0, status=STATUS_SKIPPED,
            skip_reason="not_applicable_city_only", required_for_goal=False,
            execution_method="none")
        self.assertEqual(record["skip_reason"], "not_applicable_city_only")
        self.assertFalse(record["required_for_goal"])

    def test_postcondition_evidence_missing_file_rejected(self):
        with self.assertRaises(ValueError):
            self.log.record_step(
                seq=3, action="search", params={}, started_at="t0", ended_at="t1",
                duration_ms=1, status=STATUS_OK, evidence_ref=None,
                postcondition_evidence=[{"key": "keyword_echo",
                                         "evidence_ref": "evidence/ghost.png",
                                         "sha256": "ab" * 4, "verified_at": "t1",
                                         "run_id": "r1"}])


class GoalOutcomeTests(unittest.TestCase):
    """S1.2 语义：必要性与终局状态只从计划推导；recorded required_for_goal 不再采信。
    旧契约（requiredness 取自记录步骤）正是评审 R1 否定的绕过路径——本类改写为新契约。"""

    def test_all_required_ok_is_satisfied(self):
        steps = [{"action": "open_site", "status": STATUS_OK, "attempt": 1},
                 {"action": "search", "status": STATUS_OK, "attempt": 1},
                 {"action": "resolve_location", "status": STATUS_SKIPPED, "attempt": 1}]
        planned = {"open_site": {"required_for_goal": True},
                   "search": {"required_for_goal": True},
                   "resolve_location": {"required_for_goal": False}}
        self.assertEqual(compute_goal_outcome(steps, planned=planned), "satisfied")

    def test_required_skipped_blocks_goal(self):
        steps = [{"action": "open_site", "status": STATUS_OK, "attempt": 1},
                 {"action": "search", "status": STATUS_SKIPPED, "attempt": 1,
                  "required_for_goal": False,  # 记录自报可选——S1.2 起不再采信
                  "skip_reason": "city_context_carried_by_url"}]
        planned = {"open_site": {"required_for_goal": True},
                   "search": {"required_for_goal": True}}
        # 计划中 search 必要 → 终局 skipped → blocked（记录自报不能改变）
        self.assertEqual(compute_goal_outcome(steps, planned=planned), "blocked")

    def test_required_failed_is_failed(self):
        steps = [{"action": "open_site", "status": STATUS_OK, "attempt": 1},
                 {"action": "search", "status": STATUS_FAILED, "attempt": 2}]
        planned = {"open_site": {"required_for_goal": True},
                   "search": {"required_for_goal": True}}
        self.assertEqual(compute_goal_outcome(steps, planned=planned), "failed")

    def test_required_waiting_user_blocks(self):
        steps = [{"action": "search", "status": STATUS_WAITING_USER, "attempt": 1}]
        planned = {"search": {"required_for_goal": True}}
        self.assertEqual(compute_goal_outcome(steps, planned=planned), "blocked")

    def test_no_required_steps_is_partial(self):
        self.assertEqual(compute_goal_outcome([], planned={}), "partial")
        self.assertEqual(compute_goal_outcome(
            [{"action": "resolve_location", "status": STATUS_OK, "attempt": 1}],
            planned={"resolve_location": {"required_for_goal": False}}), "partial")

    def test_run5_history_not_retroactively_satisfied(self):
        # 口径纠正（§1）：run5 历史记录缺计划绑定 → 只能得 partial，
        # 不得把 completed 会话追认成四动作成功
        steps = [{"seq": 1, "status": STATUS_OK},
                 {"seq": 2, "status": STATUS_SKIPPED},
                 {"seq": 4, "status": STATUS_OK}]
        self.assertEqual(compute_goal_outcome(steps), "partial")


class SessionEndTests(unittest.TestCase):
    def test_finish_records_dual_outcome(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            import argparse
            prep_out = []
            import contextlib
            with contextlib.redirect_stdout(_ListWriter(prep_out)):
                from executor.run_session import cmd_prepare
                cmd_prepare(argparse.Namespace(
                    command="prepare", customer_ref="synthetic", city="杭州",
                    keyword="生日餐厅", base=str(base)))
            session = Path(json.loads(prep_out[-1])["session_dir"])
            log = ExecutionLog(session)
            rel, sha = evidence(session)
            log.record_step(seq=1, action="open_site", params={}, started_at="t0",
                            ended_at="t1", duration_ms=10, status=STATUS_OK,
                            evidence_ref=f"{rel}#sha256:{sha}",
                            action_source="automation", execution_method="direct_navigation",
                            required_for_goal=True,
                            postcondition_evidence=[{"key": "k", "evidence_ref": rel,
                                                     "sha256": sha, "verified_at": "t1",
                                                     "run_id": "x"}])
            out = []
            with contextlib.redirect_stdout(_ListWriter(out)):
                cmd_finish(argparse.Namespace(
                    command="finish", session_dir=str(session), outcome="completed",
                    goal_outcome=None, note="双结局测试"))
            result = json.loads(out[-1])
            # completed 的运行仍可能不是目标满足：本例缺 search 必要动作 → blocked
            self.assertEqual(result["run_outcome"], "completed")
            self.assertEqual(result["goal_outcome"], "blocked")
            lines = log.load_lines()
            self.assertEqual(lines[-1]["type"], "session_end")
            self.assertEqual(lines[-1]["run_outcome"], "completed")
            self.assertEqual(lines[-1]["goal_outcome"], "blocked")
            summary = (session / "summary.md").read_text(encoding="utf-8")
            self.assertIn("goal_outcome", summary)


class ReleaseGateTests(unittest.TestCase):
    """§4.2 裁决表逐条验证。"""

    def _policy(self, **overrides):
        policy = {"policy_version": "p1",
                  "required_checks": ["json_compliance", "budget_coverage", "privacy_leak"],
                  "min_samples_per_scenario": {"json_compliance": 20, "budget_coverage": 20,
                                                "privacy_leak": 20},
                  "metric_thresholds": {"runtime_json_compliance": {"min": 0.95}},
                  "evidence_freshness_days": 365,
                  "allowed_sources": ["synthetic", "observed"]}
        policy.update(overrides)
        return policy

    def _report(self, **overrides):
        report = {"schema_version": "1", "run_id": "run-x", "evaluated_at": "2026-11-16",
                  "model_hash": "a" * 16, "template_hash": "b" * 16, "dataset_hash": "c" * 16,
                  "evaluator_version": "ev1",
                  "required_checks": ["json_compliance", "budget_coverage", "privacy_leak"],
                  "completed_checks": [
                      {"check": "json_compliance", "applicable": True,
                       "sample_ids": [f"s{i}" for i in range(20)],
                       "sources": ["synthetic"], "evidence_verified_at": "2026-11-15"},
                      {"check": "budget_coverage", "applicable": True,
                       "sample_ids": [f"b{i}" for i in range(20)],
                       "budget_applicable": True, "amounts_cents": [50000] * 20,
                       "sources": ["synthetic"], "evidence_verified_at": "2026-11-15"},
                      {"check": "privacy_leak", "applicable": True,
                       "sample_ids": [f"p{i}" for i in range(20)],
                       "sources": ["synthetic"], "evidence_verified_at": "2026-11-15"}],
                  "sample_counts": {"json_compliance": 20, "budget_coverage": 20,
                                     "privacy_leak": 20},
                  "findings": [], "metrics": {"runtime_json_compliance": 0.96}}
        report.update(overrides)
        return report

    def test_pass_when_all_complete(self):
        gate = evaluate_release_gate(self._report(), self._policy())
        self.assertEqual(gate["decision"], "pass")

    def test_missing_report_field_is_incomplete(self):
        report = self._report()
        report.pop("model_hash")
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")
        self.assertIn("报告不符合契约", gate["reasons"][0])

    def test_empty_samples_incomplete(self):
        report = self._report(completed_checks=[])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")

    def test_budget_amount_missing_incomplete(self):
        report = self._report(completed_checks=[
            {"check": "json_compliance", "applicable": True,
             "sample_ids": [f"s{i}" for i in range(20)],
             "sources": ["synthetic"], "evidence_verified_at": "2026-11-15"},
            {"check": "budget_coverage", "applicable": True,
             "sample_ids": [f"b{i}" for i in range(20)],
             "budget_applicable": True, "amounts_cents": [-1, 50000],
             "sources": ["synthetic"], "evidence_verified_at": "2026-11-15"},
            {"check": "privacy_leak", "applicable": True,
             "sample_ids": [f"p{i}" for i in range(20)],
             "sources": ["synthetic"], "evidence_verified_at": "2026-11-15"}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")
        self.assertTrue(any("金额" in r for r in gate["reasons"]))

    def test_duplicate_samples_do_not_count(self):
        report = self._report(completed_checks=[
            {"check": "json_compliance", "applicable": True, "sample_ids": ["s1"] * 20,
             "sources": ["synthetic"], "evidence_verified_at": "2026-11-15"},
            {"check": "budget_coverage", "applicable": True,
             "sample_ids": [f"b{i}" for i in range(20)],
             "budget_applicable": True, "amounts_cents": [50000] * 20,
             "sources": ["synthetic"], "evidence_verified_at": "2026-11-15"},
            {"check": "privacy_leak", "applicable": True,
             "sample_ids": [f"p{i}" for i in range(20)],
             "sources": ["synthetic"], "evidence_verified_at": "2026-11-15"}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")
        self.assertTrue(any("重复样本" in r for r in gate["reasons"]))

    def test_normal_exclusion_is_not_an_error(self):
        report = self._report(findings=[{"type": "budget_normal_exclusion",
                                          "detail": "172×4 超界被筛除"}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "pass")
        self.assertEqual(gate["counts"]["budget_normal_exclusion"], 1)

    def test_override_recommendation_fails(self):
        report = self._report(findings=[{"type": "budget_override_recommendation",
                                          "detail": "推荐组合最坏688超600"}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "fail")

    def test_privacy_leak_fails(self):
        report = self._report(findings=[{"type": "privacy_leak", "detail": "事件原文外发"}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "fail")

    def test_not_applicable_requires_reason_and_policy(self):
        # §4.2：不适用检查须"明确理由 + 策略允许"两者齐备，不当作已通过样本
        report = self._report(completed_checks=[
            {"check": "json_compliance", "applicable": True,
             "sample_ids": [f"s{i}" for i in range(20)]},
            {"check": "budget_coverage", "applicable": False},  # 无理由
            {"check": "privacy_leak", "applicable": True,
             "sample_ids": [f"p{i}" for i in range(20)]}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")
        # 策略允许但仍无理由 → incomplete
        gate2 = evaluate_release_gate(report, self._policy(not_applicable_allowed=["budget_coverage"]))
        self.assertEqual(gate2["decision"], "incomplete")
        # 理由 + 策略允许 → 记 not_applicable，其余完成 → pass
        report2 = self._report(completed_checks=[
            {"check": "json_compliance", "applicable": True,
             "sample_ids": [f"s{i}" for i in range(20)],
             "sources": ["synthetic"], "evidence_verified_at": "2026-11-15"},
            {"check": "budget_coverage", "applicable": False,
             "not_applicable_reason": "本评测集不含预算场景"},
            {"check": "privacy_leak", "applicable": True,
             "sample_ids": [f"p{i}" for i in range(20)],
             "sources": ["synthetic"], "evidence_verified_at": "2026-11-15"}])
        gate3 = evaluate_release_gate(report2, self._policy(not_applicable_allowed=["budget_coverage"]))
        self.assertEqual(gate3["decision"], "pass")
        self.assertEqual(gate3["counts"]["not_applicable_checks"], 1)

    def test_metric_threshold_miss_is_incomplete(self):
        gate = evaluate_release_gate(self._report(metrics={"runtime_json_compliance": 0.80}),
                                     self._policy())
        self.assertEqual(gate["decision"], "incomplete")
        self.assertTrue(any("未达标" in r for r in gate["reasons"]))

    def test_policy_must_be_configured(self):
        gate = evaluate_release_gate(self._report(), {"policy_version": "p1"})
        self.assertEqual(gate["decision"], "incomplete")
        self.assertIn("策略不符合契约", gate["reasons"][0])


class PlanFingerprintTests(unittest.TestCase):
    def test_budget_fingerprint_stable_and_bound(self):
        plan = build_plan(customer())
        self.assertIsNotNone(plan["budget_fingerprint"])
        self.assertEqual(len(plan["budget_fingerprint"]), 16)
        plan2 = build_plan(customer())
        self.assertEqual(plan["budget_fingerprint"], plan2["budget_fingerprint"])
        other = build_plan(dict(customer(), party_size=2))
        self.assertNotEqual(plan["budget_fingerprint"], other["budget_fingerprint"])
        validate(plan, load_schema("plan.schema.json"))


class _ListWriter:
    def __init__(self, sink):
        self.sink = sink

    def write(self, text):
        text = text.strip()
        if text:
            self.sink.append(text)

    def flush(self):
        pass


if __name__ == "__main__":
    unittest.main()
