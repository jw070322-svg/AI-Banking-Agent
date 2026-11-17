"""试点台账 v2 测试（S1.1，修复评审 R2）。

每项对应一个评审复现缺陷的 failing-before / passing-after：
- 默认路径 TypeError（评审复现）→ _ledger_path(None) 返回 DEFAULT_LEDGER
- start 接受不存在会话路径 → 现拒绝
- finish 接受空证据 + 断言 satisfied → 现从会话推导并要求全哈希证据
- 全部 waiting_user 记为墙 → 现仅确认墙原因
- 0 运行产出率值 → 现 not_evaluated
全部使用临时目录与合成台账行；台账层的合成行仅作测试fixture。"""
import json
import tempfile
import unittest
from pathlib import Path

from pilot_ledger import (DEFAULT_LEDGER, REAL_SOURCE_KIND, _ledger_path, finish,
                          start, stats, verify)

WALL_MARKER = "滑动验证"  # 必须命中 executor.base.FORCE_WALL_KEYWORDS


def write_session(session: Path, *, run_outcome, goal_outcome,
                  steps=None, takeover_step=False):
    session.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "run_start", "timestamp": "t0", "run_id": "r-" + session.name,
              "customer_ref": "c-real-1", "mode": "readonly_observation"}]
    for step in (steps or []):
        lines.append(step)
    lines.append({"type": "session_end", "timestamp": "t1", "run_id": "r-" + session.name,
                  "run_outcome": run_outcome, "goal_outcome": goal_outcome,
                  "finished_at": "t1"})
    (session / "run.jsonl").write_text(
        "\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n",
        encoding="utf-8")
    return session


def ok_step(**overrides):
    step = {"type": "step", "timestamp": "t", "seq": 1, "action": "open_site",
            "params": {}, "started_at": "t0", "ended_at": "t1", "duration_ms": 10,
            "status": "ok", "retries": 0, "error_code": None,
            "response_summary": "官网可达", "evidence_ref": None,
            "action_source": "automation", "execution_method": "direct_navigation",
            "skip_reason": None, "required_for_goal": True,
            "postcondition_evidence": None}
    step.update(overrides)
    return step


def wall_step():
    return ok_step(action="open_site", status="waiting_user", error_code="verification_wall",
                   response_summary=f"页面出现{WALL_MARKER}（转用户接管）",
                   action_source="user_takeover")


def real_source_file(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kind": "local_real_file", "source_version": "2026-11-14",
                                "records": records}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return str(path)


class DefaultPathTests(unittest.TestCase):
    def test_ledger_path_none_returns_default(self):
        # failing-before：stats() 无参调用曾因 Path(None) 崩溃（评审复现）
        self.assertEqual(_ledger_path(None), DEFAULT_LEDGER)

    def test_stats_no_arg_does_not_crash(self):
        # 若默认台账尚无内容，应返回 not_evaluated 而非异常
        if not DEFAULT_LEDGER.is_file():
            result = stats()
            self.assertEqual(result["status"], "not_evaluated")


class StartTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)
        self.session = write_session(self.base / "sess-1", run_outcome="completed",
                                     goal_outcome="satisfied")
        self.source = real_source_file(self.base / "real.json", [
            {"record_id": "c-real-1", "city": "杭州", "special_event": "生日聚餐",
             "budget": {"max": "600", "currency": "CNY", "basis": "total"},
             "party_size": 4}])
        self.source_kind = REAL_SOURCE_KIND

    def tearDown(self):
        self._temp.cleanup()

    def start(self, record_id="c-real-1", city="杭州", session=None, **overrides):
        return start(record_id, overrides.pop("scenario", "normal"), city,
                     overrides.pop("source_kind", self.source_kind),
                     overrides.pop("session_dir", str(session or self.session)),
                     source_path=overrides.pop("source_path", self.source),
                     ledger=self.ledger if overrides.pop("use_ledger", False)
                     else overrides.pop("ledger", self.ledger),
                     **overrides)

    def setUp_ledger(self):
        self.ledger = str(self.base / "ledger.jsonl")

    def test_start_happy_path_derives_city(self):
        row = start("c-real-1", "normal", "杭州", REAL_SOURCE_KIND, str(self.session),
                    source_path=self.source, ledger=str(self.base / "ledger.jsonl"))
        self.assertEqual(row["city"], "杭州")  # 从来源记录推导

    def test_nonexistent_session_rejected(self):
        # failing-before：start 曾接受不存在的 session 路径（评审复现）
        with self.assertRaises(ValueError):
            start("c-real-1", "normal", "杭州", REAL_SOURCE_KIND,
                  str(self.base / "no-such"), source_path=self.source,
                  ledger=str(self.base / "l.json"))

    def test_session_without_run_jsonl_rejected(self):
        empty = self.base / "empty-sess"
        empty.mkdir()
        with self.assertRaises(ValueError):
            start("c-real-1", "normal", "杭州", REAL_SOURCE_KIND, str(empty),
                  source_path=self.source, ledger=str(self.base / "l.json"))

    def test_missing_source_path_rejected(self):
        with self.assertRaises(ValueError):
            start("c-real-1", "normal", "杭州", REAL_SOURCE_KIND, str(self.session),
                  source_path=None, ledger=str(self.base / "l.json"))

    def test_record_not_found_rejected(self):
        with self.assertRaises(ValueError):
            start("c-nope", "normal", "杭州", REAL_SOURCE_KIND, str(self.session),
                  source_path=self.source, ledger=str(self.base / "l.json"))

    def test_duplicate_record_in_source_rejected(self):
        src = real_source_file(self.base / "dup.json", [
            {"record_id": "c-real-1", "city": "杭州", "special_event": "a",
             "budget": {"max": "1", "currency": "CNY", "basis": "total"}},
            {"record_id": "c-real-1", "city": "上海", "special_event": "b",
             "budget": {"max": "2", "currency": "CNY", "basis": "total"}}])
        with self.assertRaises(ValueError):
            start("c-real-1", "normal", "杭州", REAL_SOURCE_KIND, str(self.session),
                  source_path=src, ledger=str(self.base / "l.json"))

    def test_synthetic_flagged_record_rejected_despite_label(self):
        # failing-before：调用方 local_real_file 标签曾可包装合成记录（评审复现）
        src = real_source_file(self.base / "fake-real.json", [
            {"record_id": "c-fake", "city": "杭州", "special_event": "生日",
             "budget": {"max": "100", "currency": "CNY", "basis": "total"},
             "synthetic": True}])
        with self.assertRaises(ValueError):
            start("c-fake", "normal", "杭州", REAL_SOURCE_KIND, str(self.session),
                  source_path=src, ledger=str(self.base / "l.json"))

    def test_cross_customer_city_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            start("c-real-1", "normal", "上海", REAL_SOURCE_KIND, str(self.session),
                  source_path=self.source, ledger=str(self.base / "l.json"))

    def test_duplicate_open_pilot_rejected(self):
        ledger = str(self.base / "ledger.jsonl")
        start("c-real-1", "normal", "杭州", REAL_SOURCE_KIND, str(self.session),
              source_path=self.source, ledger=ledger)
        with self.assertRaises(ValueError):
            start("c-real-1", "normal", "杭州", REAL_SOURCE_KIND, str(self.session),
                  source_path=self.source, ledger=ledger)


class FinishTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)
        self.ledger = str(self.base / "ledger.jsonl")
        self.session = write_session(self.base / "sess-ok", run_outcome="completed",
                                     goal_outcome="satisfied")
        self.source = real_source_file(self.base / "real.json", [
            {"record_id": "c-real-1", "city": "杭州", "special_event": "生日聚餐",
             "budget": {"max": "600", "currency": "CNY", "basis": "total"},
             "party_size": 4}])
        self.pilot = start("c-real-1", "normal", "杭州", REAL_SOURCE_KIND,
                           str(self.session), source_path=self.source,
                           ledger=self.ledger)["pilot_id"]

    def tearDown(self):
        self._temp.cleanup()

    def _evidence(self, name="a.png", content=b"png", session=None):
        session = Path(session) if session else self.session
        f = session / "evidence" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content)
        from executor.base import sha256_of
        return f"evidence/{name}#sha256:{sha256_of(f)}"

    def test_finish_derives_outcomes_from_session(self):
        row = finish(self.pilot, evidence_refs=[self._evidence()], ledger=self.ledger)
        self.assertEqual(row["run_outcome"], "completed")
        self.assertEqual(row["goal_outcome"], "satisfied")
        self.assertFalse(row["user_takeover"])

    def test_inconsistent_cli_assertion_rejected(self):
        # failing-before：CLI 曾可断言 satisfied 而会话并非如此（评审复现）
        with self.assertRaises(ValueError):
            finish(self.pilot, run_outcome="waiting_user", ledger=self.ledger)

    def test_empty_evidence_rejected(self):
        # failing-before：空证据 + 断言 satisfied 曾被接受（评审复现）
        with self.assertRaises(ValueError):
            finish(self.pilot, evidence_refs=[], ledger=self.ledger)

    def test_prefix_hash_evidence_rejected(self):
        # failing-before：前缀哈希曾被接受（评审复现）
        with self.assertRaises(ValueError):
            finish(self.pilot, evidence_refs=["evidence/a.png#sha256:abcd"],
                   ledger=self.ledger)

    def test_unfinalized_session_rejected(self):
        session = self.base / "sess-open"
        session.mkdir()
        (session / "run.jsonl").write_text(
            json.dumps({"type": "run_start", "timestamp": "t", "run_id": "r"}) + "\n",
            encoding="utf-8")
        pilot = start("c-real-1", "negation", "杭州", REAL_SOURCE_KIND, str(session),
                      source_path=self.source, ledger=self.ledger)["pilot_id"]
        with self.assertRaises(ValueError):
            finish(pilot, evidence_refs=[self._evidence()], ledger=self.ledger)

    def test_wall_classification_requires_confirmed_marker(self):
        # failing-before：所有 waiting_user 都被计为墙阻断（评审复现）
        wall_session = write_session(self.base / "sess-wall", run_outcome="waiting_user",
                                     goal_outcome="blocked", steps=[wall_step()])
        plain_session = write_session(self.base / "sess-plain", run_outcome="waiting_user",
                                      goal_outcome="blocked")
        ledger = str(self.base / "ledger-walls.jsonl")
        p1 = start("c-real-1", "verification_wall", "杭州", REAL_SOURCE_KIND,
                   str(wall_session), source_path=self.source, ledger=ledger)["pilot_id"]
        ev = self._evidence("wall.png", session=wall_session)
        finish(p1, evidence_refs=[ev], ledger=ledger)
        p2 = start("c-real-1", "no_result", "杭州", REAL_SOURCE_KIND,
                   str(plain_session), source_path=self.source, ledger=ledger)["pilot_id"]
        finish(p2, evidence_refs=[self._evidence("plain.png", session=plain_session)],
               ledger=ledger)
        result = stats(ledger)
        self.assertEqual(result["counts"]["wall_blocked"], 1)  # 仅确认墙原因

    def test_takeover_derived_from_session(self):
        ledger = str(self.base / "ledger-t.jsonl")
        takeover_session = write_session(
            self.base / "sess-takeover", run_outcome="waiting_user",
            goal_outcome="blocked", steps=[wall_step()])
        p = start("c-real-1", "verification_wall", "杭州", REAL_SOURCE_KIND,
                  str(takeover_session), source_path=self.source, ledger=ledger)["pilot_id"]
        row = finish(p, evidence_refs=[self._evidence("t.png", session=takeover_session)],
                     ledger=ledger)
        self.assertTrue(row["user_takeover"])


class StatsTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)
        self.ledger = str(self.base / "ledger.jsonl")
        self.source = real_source_file(self.base / "real.json", [
            {"record_id": "c-real-1", "city": "杭州", "special_event": "生日聚餐",
             "budget": {"max": "600", "currency": "CNY", "basis": "total"},
             "party_size": 4},
            {"record_id": "c-real-2", "city": "上海", "special_event": "纪念日",
             "budget": {"max": "800", "currency": "CNY", "basis": "total"},
             "party_size": 2}])

    def tearDown(self):
        self._temp.cleanup()

    def _cycle(self, pilot_id, scenario, city, session_name, record_id="c-real-1",
               run_outcome="completed", goal_outcome="satisfied", steps=None):
        session = write_session(self.base / session_name, run_outcome=run_outcome,
                                goal_outcome=goal_outcome, steps=steps)
        ev = session / "evidence" / "a.png"
        ev.parent.mkdir(parents=True, exist_ok=True)
        ev.write_bytes(b"png")
        from executor.base import sha256_of
        p = start(record_id, scenario, city, REAL_SOURCE_KIND, str(session),
                  source_path=self.source, ledger=self.ledger)["pilot_id"]
        finish(p, evidence_refs=[f"evidence/a.png#sha256:{sha256_of(ev)}"],
               ledger=self.ledger)

    def test_zero_runs_not_evaluated(self):
        # failing-before：0 运行曾产出率值（评审复现）
        result = stats(self.ledger)
        self.assertEqual(result["status"], "not_evaluated")
        self.assertNotIn("overall_success_rate", result)

    def test_counts_and_rates_with_numerators(self):
        self._cycle("P-a", "normal", "杭州", "s1")                     # satisfied
        self._cycle("P-b", "negation", "上海", "s2", record_id="c-real-2")  # satisfied·第二城
        self._cycle("P-c", "verification_wall", "上海", "s3", record_id="c-real-2",
                    run_outcome="waiting_user", goal_outcome="blocked",
                    steps=[wall_step()])                                # 墙阻断
        self._cycle("P-d", "multi_category", "杭州", "s4",
                    run_outcome="aborted", goal_outcome="failed")       # 失败
        result = stats(self.ledger)
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["closed"], 4)
        self.assertEqual(result["auto_completion_rate"], 0.5)
        self.assertEqual(result["user_takeover_rate"], 0.25)
        self.assertEqual(result["controlled_environment_completion_rate"], 0.6667)  # 2/(4−1)
        self.assertEqual(result["overall_success_rate"], 0.5)
        self.assertEqual(result["rate_numerators_denominators"]["overall_success"], "2/4")
        self.assertIn("no_result", result["missing_scenarios"])
        self.assertIn("price_missing", result["missing_scenarios"])

    def test_invalid_row_reported_not_counted(self):
        rows = [{"type": "pilot_run", "pilot_id": "P-bad", "scenario": "unknown_x",
                 "city": "杭州", "source_kind": REAL_SOURCE_KIND,
                 "record_id": "c-real-1", "session_dir": "s",
                 "run_outcome": "completed", "goal_outcome": "satisfied"}]
        Path(self.ledger).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
        result = stats(self.ledger)
        self.assertEqual(result["closed"], 0)
        self.assertEqual(len(result["invalid"]), 1)


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)
        self.ledger = str(self.base / "ledger.jsonl")

    def tearDown(self):
        self._temp.cleanup()

    def _row_with_refs(self, refs):
        session = self.base / "sess"
        session.mkdir(exist_ok=True)
        return {"type": "pilot_run", "pilot_id": "P-001", "record_id": "c-real-1",
                "scenario": "normal", "city": "杭州", "source_kind": REAL_SOURCE_KIND,
                "session_dir": str(session), "evidence_refs": refs}

    def test_prefix_hash_is_a_finding(self):
        # failing-before：verify 曾接受前缀比较（评审复现）
        Path(self.ledger).write_text(json.dumps(
            self._row_with_refs(["evidence/a.png#sha256:abcd"]), ensure_ascii=False) + "\n",
            encoding="utf-8")
        result = verify(self.ledger, base_dir=self.base)
        self.assertFalse(result["pass"])
        self.assertIn("hash_format_invalid", [f["status"] for f in result["findings"]])

    def test_missing_and_matching_evidence(self):
        good = self.base / "sess" / "evidence" / "a.png"
        good.parent.mkdir(parents=True)
        good.write_bytes(b"png")
        from executor.base import sha256_of
        rows = [self._row_with_refs(
            [f"evidence/a.png#sha256:{sha256_of(good)}",
             f"evidence/ghost.png#sha256:{'b' * 64}"])]
        Path(self.ledger).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
        result = verify(self.ledger, base_dir=self.base)
        statuses = [f["status"] for f in result["findings"]]
        self.assertIn("evidence_missing", statuses)
        self.assertNotIn("hash_format_invalid", statuses)
        self.assertFalse(result["pass"])  # 有发现即不通过


if __name__ == "__main__":
    unittest.main()
