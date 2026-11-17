"""工作包A补充：S1.2 R1 结局权威性验收测试（评审原文四例 + 重试/终局/篡改防护）。

前置：prepare 冻结计划（plan_hash + step_id）；record 按计划对账、机器裁决先于
落盘；finish 机器 goal_outcome 与人工注解分离。全部合成数据 + 临时目录。"""
import argparse
import contextlib
import json
import tempfile
import unittest
from pathlib import Path

from executor.base import ExecutionLog
from executor.run_session import cmd_finish, cmd_prepare, cmd_record
from schema_check import load_schema, validate

from test_work_package_a import _ListWriter


class R1OutcomeAuthorityTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)
        out = []
        with contextlib.redirect_stdout(_ListWriter(out)):
            cmd_prepare(argparse.Namespace(
                command="prepare", customer_ref="synthetic", city="杭州",
                keyword="生日餐厅", base=str(self.base)))
        self.session = Path(json.loads(out[-1])["session_dir"])
        self.plan = json.loads((self.session / "steps.json").read_text(encoding="utf-8-sig"))
        self.run_id = self.plan["run_id"]
        self.log = ExecutionLog(self.session)

    def tearDown(self):
        self._temp.cleanup()

    def _evidence(self, name):
        from executor.base import evidence_ref_for
        f = self.session / "evidence" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"evidence")
        ref = evidence_ref_for(self.session, f)
        rel, sha = ref.split("#")[0], ref.split("#sha256:", 1)[1]
        return rel, sha

    def _step_file(self, step_id, attempt, status, *, observed=None, response=None,
                   skip_reason=None, required_for_goal=None, postconditions=None,
                   error_code=None):
        seq = int(step_id.split(":")[0])
        action = step_id.split(":", 1)[1]
        plan_step = next((s for s in self.plan["steps"] if s["step_id"] == step_id), None)
        post = plan_step["postconditions"] if (plan_step and postconditions is None)             else (postconditions if postconditions is not None else [])
        rel, sha = self._evidence(
            f"{step_id.replace(':', '_')}-{attempt}.png") if status == "ok" else ("evidence/n.a", "0" * 64)
        pe = [{"key": k, "evidence_ref": rel, "sha256": sha,
               "verified_at": "t", "run_id": self.run_id}
              for k in post] if status == "ok" else []
        record = {"step_id": step_id, "attempt": attempt, "seq": seq, "action": action,
                  "params": {}, "started_at": None, "ended_at": None, "duration_ms": 10,
                  "status": status, "retries": 0, "error_code": error_code,
                  "response_summary": response or "",
                  "evidence_ref": f"{rel}#sha256:{sha}" if status == "ok" else None,
                  "action_source": "automation", "execution_method": "direct_navigation",
                  "postconditions": post, "postcondition_evidence": pe}
        if observed is not None:
            record["observed_state"] = observed
        if skip_reason is not None:
            record["skip_reason"] = skip_reason
        if required_for_goal is not None:
            record["required_for_goal"] = required_for_goal
        path = self.session / f"step-{step_id.replace(':', '_')}-{attempt}.json"
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return path

    def _record(self, path, expect_error=False):
        out = []
        with contextlib.redirect_stdout(_ListWriter(out)):
            code = cmd_record(argparse.Namespace(
                command="record", session_dir=str(self.session), step_file=str(path)))
        if expect_error:
            return code, None
        return code, json.loads(out[-1])

    def _finish(self, goal_outcome=None):
        out = []
        with contextlib.redirect_stdout(_ListWriter(out)):
            cmd_finish(argparse.Namespace(
                command="finish", session_dir=str(self.session), outcome="completed",
                goal_outcome=goal_outcome, note="R1测试"))
        return json.loads(out[-1])

    def test_machine_verdict_persisted_with_step(self):
        code, result = self._record(self._step_file(
            "1:open_site", 1, "ok",
            observed={"domain_is_dianping": True, "title_nonempty": True}))
        self.assertEqual(code, 0)
        self.assertEqual(result["verdict"], "CONTINUE")
        rows = self.log.load_lines()
        step = next(r for r in rows if r.get("type") == "step")
        self.assertEqual(step["machine_verdict"], "CONTINUE")
        self.assertEqual(step["plan_hash"], self.plan["plan_hash"])
        self.assertEqual(step["required_for_goal"], True)  # 来自计划

    def test_skipped_mandatory_search_cannot_satisfy(self):
        # 评审验收①：谎报必需的 skipped search —— 记录当场被拒（必要性与计划不符），
        # 且 search 永未有效记录 → 目标 blocked，不能得 satisfied
        self._record(self._step_file("1:open_site", 1, "ok",
                    observed={"domain_is_dianping": True, "title_nonempty": True}))
        with self.assertRaises(ValueError):
            self._record(self._step_file("4:search", 1, "skipped",
                        skip_reason="claimed_optional", required_for_goal=False))
        result = self._finish()
        self.assertEqual(result["goal_outcome"], "blocked")

    def test_explicit_goal_override_is_annotation_only(self):
        # 评审验收④：显式 success 覆盖仅成为注解
        self._record(self._step_file("1:open_site", 1, "ok",
                    observed={"domain_is_dianping": True, "title_nonempty": True}))
        result = self._finish(goal_outcome="satisfied")
        self.assertEqual(result["goal_outcome"], "blocked")
        self.assertEqual(result["goal_outcome_annotation"], "satisfied")
        session_end = self.log.load_lines()[-1]
        self.assertEqual(session_end["goal_outcome"], "blocked")
        self.assertEqual(session_end["goal_outcome_annotation"], "satisfied")

    def test_required_for_goal_tamper_rejected(self):
        with self.assertRaises(ValueError):
            self._record(self._step_file("4:search", 1, "skipped",
                        skip_reason="claimed_optional", required_for_goal=False))

    def test_postconditions_tamper_rejected(self):
        with self.assertRaises(ValueError):
            self._record(self._step_file("4:search", 1, "ok",
                        postconditions={}, observed={"keyword_echo": True,
                                                      "city_consistent": True}))

    def test_unplanned_step_id_rejected(self):
        with self.assertRaises(ValueError):
            self._record(self._step_file("9:hack_site", 1, "ok",
                        observed={"anything": True}))

    def test_plan_tamper_rejected(self):
        plan_path = self.session / "steps.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
        plan["steps"][0]["verify"] = "被篡改的验证文本"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ValueError):
            self._record(self._step_file("1:open_site", 1, "ok",
                        observed={"domain_is_dianping": True, "title_nonempty": True}))

    def test_attempt_monotonic_rejected(self):
        code, _ = self._record(self._step_file("4:search", 1, "failed",
                                                error_code="timeout"))
        with self.assertRaises(ValueError):
            self._record(self._step_file("4:search", 1, "failed",
                                          error_code="timeout"))
        # 递增尝试被接受
        code2, _ = self._record(self._step_file("4:search", 2, "failed",
                                                 error_code="timeout"))
        self.assertEqual(code2, 1)  # RETRY 裁决 → 退出码1，但记录成功

    def test_retry_terminal_attempt_counts_once(self):
        # 评审验收⑤：失败后重试成功按终局尝试计一次目标
        self._record(self._step_file("1:open_site", 1, "ok",
                    observed={"domain_is_dianping": True, "title_nonempty": True}))
        self._record(self._step_file("2:select_city", 1, "ok",
                    observed={"selected_city_matches": True}))
        self._record(self._step_file("4:search", 1, "failed", error_code="timeout"))
        self._record(self._step_file("4:search", 2, "ok",
                    observed={"keyword_echo": True, "city_consistent": True}))
        result = self._finish()
        self.assertEqual(result["goal_outcome"], "satisfied")
        attempt_rows = [r for r in self.log.load_lines()
                        if r.get("type") == "step" and r.get("step_id") == "4:search"]
        self.assertEqual(len(attempt_rows), 2)  # 两次尝试都留痕
        self.assertEqual(result["steps"], 4)    # 目标只算一次

    def test_satisfied_happy_path_with_machine_verdicts(self):
        self._record(self._step_file("1:open_site", 1, "ok",
                    observed={"domain_is_dianping": True, "title_nonempty": True}))
        self._record(self._step_file("2:select_city", 1, "ok",
                    observed={"selected_city_matches": True}))
        self._record(self._step_file("3:resolve_location", 1, "skipped",
                    skip_reason="not_applicable_city_only"))
        self._record(self._step_file("4:search", 1, "ok",
                    observed={"keyword_echo": True, "city_consistent": True}))
        result = self._finish()
        self.assertEqual(result["goal_outcome"], "satisfied")
        for row in self.log.load_lines():
            if row.get("type") == "step":
                self.assertEqual(row["machine_verdict"], "CONTINUE")

    def test_duplicate_finalize_rejected(self):
        self._record(self._step_file("1:open_site", 1, "ok",
                    observed={"domain_is_dianping": True, "title_nonempty": True}))
        self._finish()
        with self.assertRaises(ValueError):
            self._finish()

    def test_post_finalize_record_rejected(self):
        self._record(self._step_file("1:open_site", 1, "ok",
                    observed={"domain_is_dianping": True, "title_nonempty": True}))
        self._finish()
        with self.assertRaises(ValueError):
            self._record(self._step_file("2:select_city", 1, "ok",
                        observed={"selected_city_matches": True}))


if __name__ == "__main__":
    unittest.main()
