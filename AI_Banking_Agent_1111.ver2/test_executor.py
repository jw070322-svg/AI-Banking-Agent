"""executor 包纯本地测试：日志契约、证据哈希防伪造、waiting_user 状态机、
重试策略、定位符注册表、会话裁决与三段式流程（不启动浏览器、不访问网络）。"""
import json
import tempfile
import unittest
from pathlib import Path

from executor.base import (STATUS_FAILED, STATUS_OK, STATUS_SKIPPED,
                           STATUS_WAITING_USER, ExecutionLog, detect_waiting_user,
                           domain_matches, evidence_ref_for, needs_retry,
                           new_session_dir, sha256_of, url_host, verify_state)
from executor.locator_registry import LocatorRegistry, LocatorSpec, default_registry
from executor.readonly_actions import CONTRACTS, build_step
from executor.run_session import cmd_finish, cmd_prepare, cmd_record, decide


class SessionDirTests(unittest.TestCase):
    def test_unique_with_evidence_subdir(self):
        with tempfile.TemporaryDirectory() as temp:
            first = new_session_dir(temp)
            second = new_session_dir(temp)
            self.assertNotEqual(first, second)
            self.assertTrue((first / "evidence").is_dir())
            self.assertTrue((second / "evidence").is_dir())


class ExecutionLogTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.session = new_session_dir(self._temp.name)
        self.log = ExecutionLog(self.session)

    def tearDown(self):
        self._temp.cleanup()

    def _evidence(self, name="shot.png", content=b"png-bytes"):
        path = self.session / "evidence" / name
        path.write_bytes(content)
        return evidence_ref_for(self.session, path)

    def test_run_start_and_ok_step_roundtrip(self):
        header = self.log.run_start("example_customer.json(synthetic)")
        self.assertEqual(header["type"], "run_start")
        ref = self._evidence()
        record = self.log.record_step(seq=1, action="open_site", params={"url": "x"},
                                      started_at="t0", ended_at="t1", duration_ms=100,
                                      status=STATUS_OK, evidence_ref=ref,
                                      response_summary="官网可达")
        self.assertEqual(record["seq"], 1)
        lines = self.log.load_lines()
        self.assertEqual([line["type"] for line in lines], ["run_start", "step"])

    def test_ok_without_evidence_rejected(self):
        with self.assertRaises(ValueError):
            self.log.record_step(seq=1, action="open_site", params={},
                                 started_at="t0", ended_at="t1", duration_ms=1,
                                 status=STATUS_OK)

    def test_missing_evidence_file_rejected(self):
        with self.assertRaises(ValueError):
            self.log.record_step(seq=1, action="open_site", params={},
                                 started_at="t0", ended_at="t1", duration_ms=1,
                                 status=STATUS_OK,
                                 evidence_ref="evidence/ghost.png#sha256:abcd")

    def test_hash_mismatch_rejected(self):
        ref = self._evidence(content=b"real-bytes")
        fake = ref.split("#")[0] + "#sha256:" + "0" * 16
        with self.assertRaises(ValueError):
            self.log.record_step(seq=1, action="open_site", params={},
                                 started_at="t0", ended_at="t1", duration_ms=1,
                                 status=STATUS_OK, evidence_ref=fake)

    def test_schema_invalid_status_rejected(self):
        ref = self._evidence()
        with self.assertRaises(ValueError):
            self.log.record_step(seq=1, action="open_site", params={},
                                 started_at="t0", ended_at="t1", duration_ms=1,
                                 status="成功", evidence_ref=ref)

    def test_failed_step_allows_no_evidence(self):
        record = self.log.record_step(seq=1, action="select_city", params={},
                                      started_at="t0", ended_at="t1", duration_ms=1,
                                      status=STATUS_FAILED, error_code="timeout")
        self.assertEqual(record["error_code"], "timeout")


class StateMachineTests(unittest.TestCase):
    def test_force_wall_detected(self):
        self.assertIsNotNone(detect_waiting_user("页面显示滑动验证"))
        self.assertIsNotNone(detect_waiting_user("请输入验证码"))

    def test_normal_login_hint_not_wall(self):
        self.assertIsNone(detect_waiting_user("首页含 请登录/注册 入口与搜索框"))

    def test_verify_wall_variants_detected(self):
        # 2026-11-12 实测：点评首页重定向 verify.meituan.com 反爬验证墙
        for text in ("身份核实", "验证中心", "action=spiderindefence"):
            self.assertIsNotNone(detect_waiting_user(text), text)

    def test_domain_match_uses_host_not_substring(self):
        # 实测教训：子串包含会把回调参数里的域名误判为当前站点
        callback_url = ("https://verify.meituan.com/v2/app/general_page"
                        "?succCallbackUrl=https%3A%2F%2Fwww.dianping.com%2F")
        self.assertFalse(domain_matches(callback_url, "www.dianping.com"))
        self.assertEqual(url_host(callback_url), "verify.meituan.com")
        self.assertTrue(domain_matches("https://www.dianping.com/", "www.dianping.com"))

    def test_verify_state(self):
        ok, _ = verify_state({"city": "杭州"}, {"city": "杭州"})
        self.assertTrue(ok)
        ok, message = verify_state({"city": "杭州"}, {"city": "上海"})
        self.assertFalse(ok)
        self.assertIn("city", message)
        ok, _ = verify_state({"matches": True}, {"matches": "yes"})
        self.assertTrue(ok)  # 布尔断言由采集方预算，真值即可

    def test_retry_policy(self):
        self.assertTrue(needs_retry("select_city", STATUS_FAILED, 0))
        self.assertFalse(needs_retry("select_city", STATUS_FAILED, 1))
        self.assertFalse(needs_retry("place_order", STATUS_FAILED, 0))  # 非只读动作


class RegistryTests(unittest.TestCase):
    def test_default_registry_candidates(self):
        registry = default_registry()
        hints = registry.candidates_for("search_input")
        self.assertTrue(hints)
        self.assertEqual(hints[0]["strategy"], "css")

    def test_unknown_target_raises(self):
        with self.assertRaises(KeyError):
            default_registry().candidates_for("buy_button")

    def test_transient_index_never_allowed(self):
        with self.assertRaises(ValueError):
            LocatorSpec(name="bad", description="x",
                        candidates=[{"strategy": "element_index", "value": 42}])
        for spec in default_registry().specs.values():
            for candidate in spec.candidates:
                self.assertIn(candidate["strategy"],
                              {"css", "role_name", "text", "placeholder", "testid"})

    def test_record_and_snapshot(self):
        registry = default_registry()
        registry.record("city_current", matched={"strategy": "text", "value": "上海"},
                        count=1)
        snapshot = json.loads(registry.to_json())
        self.assertEqual(snapshot["observations"]["city_current"]["count"], 1)
        # 快照记录的是策略与匹配，不记录瞬时元素编号
        self.assertNotIn("element_index", registry.to_json())


class ActionContractTests(unittest.TestCase):
    def test_unknown_action(self):
        with self.assertRaises(KeyError):
            build_step("place_order", {}, 1)

    def test_non_readonly_contract_rejected(self):
        with self.assertRaises(ValueError):
            bad = build_step("open_site", {}, 1)
            bad["read_only"] = False
            CONTRACTS["open_site"].__class__(name="x", verify="x", read_only=False)

    def test_build_step_fields(self):
        step = build_step("search", {"public_keyword": "生日餐厅", "target_city": "杭州"}, 4)
        self.assertEqual(step["seq"], 4)
        self.assertTrue(step["read_only"])
        self.assertIn("keyword_echo", step["postconditions"])


class DecideTests(unittest.TestCase):
    def base(self, **overrides):
        result = {"action": "open_site", "status": STATUS_OK,
                  "postconditions": {"domain_is_dianping": True},
                  "observed_state": {"domain_is_dianping": True},
                  "retries": 0}
        result.update(overrides)
        return result

    def test_ok_continue(self):
        self.assertEqual(decide(self.base())[0], "CONTINUE")

    def test_ok_but_mismatch_aborts(self):
        verdict, reason = decide(self.base(observed_state={"domain_is_dianping": False}))
        self.assertEqual(verdict, "ABORT")
        self.assertIn("核验失败", reason)

    def test_ok_but_captcha_waits_user(self):
        result = self.base(observed_state={"domain_is_dianping": True,
                                           "state_summary": "出现安全验证"})
        self.assertEqual(decide(result)[0], "WAITING_USER")

    def test_waiting_user(self):
        result = self.base(status=STATUS_WAITING_USER,
                           response_summary="登录墙")
        self.assertEqual(decide(result)[0], "WAITING_USER")

    def test_failed_readonly_retry_then_abort(self):
        result = self.base(status=STATUS_FAILED, action="select_city", retries=0)
        self.assertEqual(decide(result)[0], "RETRY")
        result["retries"] = 1
        self.assertEqual(decide(result)[0], "ABORT")

    def test_skipped_continues_with_reason_passthrough(self):
        result = self.base(status=STATUS_SKIPPED, action="resolve_location")
        self.assertEqual(decide(result)[0], "CONTINUE")
        result["response_summary"] = "未执行：被验证墙阻断"
        self.assertEqual(decide(result)[1], "未执行：被验证墙阻断")


class SessionFlowTests(unittest.TestCase):
    """prepare → record（含证据校验）→ finish 三段式进程内端到端。"""

    def test_full_flow(self):
        with tempfile.TemporaryDirectory() as temp:
            out = []
            import contextlib
            with contextlib.redirect_stdout(_ListWriter(out)):
                cmd_prepare(_args(command="prepare", customer_ref="synthetic", city="杭州",
                                  keyword="生日餐厅", base=temp))
            session = Path(json.loads(out[-1])["session_dir"])
            self.assertTrue((session / "steps.json").is_file())
            self.assertTrue((session / "locator_snapshot.json").is_file())

            # 步骤1：成功 + 真实证据 + 后置条件证据绑定（§4.1）
            evidence = session / "evidence" / "open_site-01.png"
            evidence.write_bytes(b"fake-png")
            ev_ref = evidence_ref_for(session, evidence)
            ev_rel, ev_sha = ev_ref.split("#")[0], ev_ref.split("#sha256:", 1)[1]
            real_run_id = json.loads((session / "steps.json").read_text(encoding="utf-8"))["run_id"]
            pe = [{"key": "domain_is_dianping", "evidence_ref": ev_rel, "sha256": ev_sha,
                   "verified_at": "t1", "run_id": real_run_id},
                  {"key": "title_nonempty", "evidence_ref": ev_rel, "sha256": ev_sha,
                   "verified_at": "t1", "run_id": real_run_id}]
            step_file = session / "step-01.json"
            step_file.write_text(json.dumps({
                "step_id": "1:open_site", "attempt": 1,
                "seq": 1, "action": "open_site", "params": {"url": "https://www.dianping.com/"},
                "started_at": "t0", "ended_at": "t1", "duration_ms": 800,
                "status": STATUS_OK, "retries": 0,
                "action_source": "automation", "execution_method": "direct_navigation",
                "required_for_goal": True,
                "postconditions": {"domain_is_dianping": True, "title_nonempty": True},
                "postcondition_evidence": pe,
                "observed_state": {"domain_is_dianping": True, "title_nonempty": True,
                                   "state_summary": "首页含 请登录/注册"},
                "evidence_ref": ev_ref,
                "response_summary": "官网可达"}, ensure_ascii=False), encoding="utf-8")
            out.clear()
            with contextlib.redirect_stdout(_ListWriter(out)):
                code = cmd_record(_args(command="record", session_dir=str(session),
                                        step_file=str(step_file)))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out[-1])["verdict"], "CONTINUE")

            # 步骤2：伪造证据 → 拒绝落盘
            bad_step = session / "step-02.json"
            bad_step.write_text(json.dumps({
                "seq": 2, "action": "select_city", "params": {},
                "started_at": "t0", "ended_at": "t1", "duration_ms": 1,
                "status": STATUS_OK, "retries": 0,
                "postconditions": {}, "observed_state": {},
                "evidence_ref": "evidence/不存在.png#sha256:abcd"}, ensure_ascii=False),
                encoding="utf-8")
            out.clear()
            with self.assertRaises(ValueError):
                cmd_record(_args(command="record", session_dir=str(session),
                                 step_file=str(bad_step)))

            # 步骤3（run2 教训回归）：声明了后置条件但 observed_state 缺键 → 拒绝落盘
            missing_key = session / "step-03.json"
            missing_key.write_text(json.dumps({
                "seq": 3, "action": "open_site", "params": {},
                "started_at": "t0", "ended_at": "t1", "duration_ms": 1,
                "status": STATUS_OK, "retries": 0,
                "postconditions": {"title_nonempty": True},
                "observed_state": {"domain_is_dianping": True},
                "evidence_ref": "evidence/open_site-01.png#sha256:"
                                + __import__("hashlib").sha256(
                                    (session / "evidence" / "open_site-01.png").read_bytes()
                                ).hexdigest()[:16]}, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                cmd_record(_args(command="record", session_dir=str(session),
                                 step_file=str(missing_key)))

            # 结束
            out.clear()
            cmd_finish(_args(command="finish", session_dir=str(session),
                             outcome="completed", goal_outcome=None, note="测试会话"))
            summary = (session / "summary.md").read_text(encoding="utf-8")
            self.assertIn("运行结局（run_outcome）：completed", summary)
            self.assertIn("目标裁决（goal_outcome）：blocked", summary)  # 缺search必要动作
            self.assertIn("只读观测", summary)


class _ListWriter:
    def __init__(self, sink):
        self.sink = sink

    def write(self, text):
        text = text.strip()
        if text:
            self.sink.append(text)

    def flush(self):
        pass


def _args(**kwargs):
    import argparse
    return argparse.Namespace(**kwargs)


if __name__ == "__main__":
    unittest.main()
