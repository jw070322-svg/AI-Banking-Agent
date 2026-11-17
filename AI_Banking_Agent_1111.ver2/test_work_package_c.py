"""工作包C测试（设计文档 §6 + 2026-11-12 反馈）：显式ID客户来源适配器、
城市映射证据登记、快照-计划接线、门禁缺口（证据时效/来源白名单）。
全部使用合成fixtures与临时目录；合成不计真实试点。"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from city_registry import (CityMappingError, build_search_url, load_city_mappings,
                           register_city_mapping, resolve_city_code, verify_city_evidence)
from customer_source import build_plan_from_snapshot, get_customer_snapshot
from evaluation.gates import evaluate_release_gate
from schema_check import load_schema, validate

ROOT = Path(__file__).parent
FIXTURES = ROOT / "data" / "customer_fixtures"


def fixture_config(name="test_customers.json", kind="test_fixture"):
    return {"type": "local_json_file", "kind": kind,
            "path": str(FIXTURES / name), "source_version": "2026-11-12"}


class CustomerSourceTests(unittest.TestCase):
    """§6 反馈重点：ID缺失/不存在/重复、跨客户串用、非法路径或JSON、口径缺失。"""

    def test_missing_id_needs_input(self):
        for bad in (None, "", "   "):
            result = get_customer_snapshot(bad, fixture_config())
            self.assertEqual(result["status"], "needs_input", bad)

    def test_record_not_found(self):
        result = get_customer_snapshot("c-nope", fixture_config())
        self.assertEqual(result["status"], "not_found")
        self.assertIn("不自动换客", result["reason"])

    def test_duplicate_record_id_detected(self):
        result = get_customer_snapshot("c-dup-1", fixture_config("duplicate_ids.json"))
        self.assertEqual(result["status"], "duplicate_record")

    def test_invalid_path_and_json(self):
        self.assertEqual(get_customer_snapshot(
            "x", {"type": "local_json_file", "kind": "test_fixture",
                  "path": "Z:/no/such.json"})["status"], "source_error")
        with tempfile.TemporaryDirectory() as temp:
            bad = Path(temp) / "bad.json"
            bad.write_text("{not-json", encoding="utf-8")
            result = get_customer_snapshot(
                "x", {"type": "local_json_file", "kind": "test_fixture", "path": str(bad)})
            self.assertEqual(result["status"], "source_error")

    def test_source_config_validation(self):
        self.assertEqual(get_customer_snapshot("c-test-001", None)["status"], "source_error")
        self.assertEqual(get_customer_snapshot(
            "c-test-001", {"type": "ftp", "kind": "test_fixture",
                            "path": "x.json"})["status"], "source_error")
        # 标记缺失 → 拒绝（测试/真实来源必须显式分开）
        result = get_customer_snapshot(
            "c-test-001", {"type": "local_json_file", "path": str(FIXTURES / "test_customers.json")})
        self.assertEqual(result["status"], "source_error")

    def test_ok_snapshot_and_isolation_between_customers(self):
        first = get_customer_snapshot("c-test-001", fixture_config())
        second = get_customer_snapshot("c-test-002", fixture_config())
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["snapshot"]["city"], "杭州")
        self.assertEqual(second["snapshot"]["city"], "上海")
        # 跨客户串用防护：不同记录指纹必然不同
        self.assertNotEqual(first["snapshot_fingerprint"], second["snapshot_fingerprint"])
        # 测试来源标记随快照传递
        self.assertEqual(first["source_kind"], "test_fixture")


class SnapshotPlanWiringTests(unittest.TestCase):
    def test_plan_binds_snapshot_and_fingerprint(self):
        snapshot = get_customer_snapshot("c-test-001", fixture_config())
        result = build_plan_from_snapshot(snapshot)
        self.assertEqual(result["status"], "planned")
        plan = result["plan"]
        self.assertIn("c-test-001@", plan["customer_ref_snapshot"])
        self.assertEqual(plan["customer_snapshot_hash"], snapshot["snapshot_fingerprint"])
        self.assertEqual(plan["source_kind"], "test_fixture")
        validate(plan, load_schema("plan.schema.json"))

    def test_budget_basis_missing_through_snapshot(self):
        snapshot = get_customer_snapshot("c-test-002", fixture_config())
        result = build_plan_from_snapshot(snapshot)
        self.assertEqual(result["status"], "needs_input")
        self.assertTrue(any("口径" in issue for issue in result["plan"]["issues"]))

    def test_not_ok_snapshot_never_builds_plan(self):
        snapshot = get_customer_snapshot("c-nope", fixture_config())
        result = build_plan_from_snapshot(snapshot)
        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["plan"])

    def test_two_customer_plans_do_not_share_binding(self):
        plan_a = build_plan_from_snapshot(get_customer_snapshot("c-test-001", fixture_config()))["plan"]
        plan_b = build_plan_from_snapshot(get_customer_snapshot("c-test-002", fixture_config()))["plan"]
        self.assertNotEqual(plan_a["customer_snapshot_hash"], plan_b["customer_snapshot_hash"])
        self.assertIn("c-test-001@", plan_a["customer_ref_snapshot"])
        self.assertIn("c-test-002@", plan_b["customer_ref_snapshot"])


class CityRegistryTests(unittest.TestCase):
    def setUp(self):
        self.mappings = load_city_mappings()

    def test_real_hangzhou_mapping_resolves(self):
        result = resolve_city_code("杭州", mappings=self.mappings)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["mapping"]["platform_city_code"], "3")

    def test_unknown_city_needs_resolution_no_guess(self):
        result = resolve_city_code("珠海", mappings=self.mappings)  # 未登记（无本地证据）
        self.assertEqual(result["status"], "needs_city_resolution")
        self.assertIn("不猜测", result["reason"])

    def test_expired_evidence_needs_resolution(self):
        future_now = datetime(2027, 1, 15, tzinfo=timezone.utc)  # 距核实日64天
        result = resolve_city_code("杭州", mappings=self.mappings,
                                    max_age_days=30, now_utc=future_now)
        self.assertEqual(result["status"], "needs_city_resolution")
        self.assertIn("证据过期", result["reason"])
        # 未过期路径（同一future下，365天窗口内）
        ok = resolve_city_code("杭州", mappings=self.mappings, max_age_days=365,
                                now_utc=future_now)
        self.assertEqual(ok["status"], "resolved")

    def test_register_requires_evidence(self):
        bad = {"city_name": "苏州", "administrative_region": "江苏省苏州市",
               "platform_city_code": "x", "source_url": "https://example.com",
               "verified_at": "2026-11-12"}  # 缺 evidence_hash
        with self.assertRaises(CityMappingError):
            register_city_mapping(bad, path=Path(tempfile.gettempdir()) / "cm-test.json")

    def test_register_conflicting_code_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "m.json"
            path.write_text(json.dumps(
                {"mappings": [dict(self.mappings["mappings"][0])]}, ensure_ascii=False),
                encoding="utf-8")
            conflict = dict(self.mappings["mappings"][0], platform_city_code="999")
            with self.assertRaises(CityMappingError):
                register_city_mapping(conflict, path=path)

    def test_verify_evidence_real_file_passes_and_tamper_detected(self):
        findings = verify_city_evidence(self.mappings, base_dir=ROOT)
        self.assertEqual(findings, [])  # 真实证据文件哈希与内容一致性全部通过
        # 篡改登记哈希 → 检出（S1.4 状态语义：unverifiable）
        tampered = {"mappings": [dict(self.mappings["mappings"][0],
                                       evidence_hash="0" * 64)]}
        findings = verify_city_evidence(tampered, base_dir=ROOT)
        self.assertEqual(findings[0]["status"], "unverifiable")
        self.assertIn("哈希不匹配", findings[0]["detail"])

    def test_build_search_url_matches_run5_verified_url(self):
        result = build_search_url("杭州", "生日餐厅", mappings=self.mappings)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["url"],
                         "https://www.dianping.com/search/keyword/3/0_%E7%94%9F%E6%97%A5%E9%A4%90%E5%8E%85")
        self.assertEqual(result["execution_method"], "direct_navigation")

    def test_build_search_url_unknown_city_passthrough(self):
        result = build_search_url("珠海", "生日餐厅", mappings=self.mappings)
        self.assertEqual(result["status"], "needs_city_resolution")

    def test_build_search_url_host_restricted(self):
        with self.assertRaises(CityMappingError):
            build_search_url("杭州", "生日餐厅", mappings=self.mappings,
                              host="evil.example.com")


class GateGapTests(unittest.TestCase):
    """A+B 门禁缺口修复的回归证明：证据时效与来源白名单强制执行。"""

    def _policy(self, **overrides):
        policy = {"policy_version": "p-c", "required_checks": ["json_compliance"],
                  "min_samples_per_scenario": {"json_compliance": 2},
                  "metric_thresholds": {"runtime_json_compliance": {"min": 0.95}},
                  "evidence_freshness_days": 7,
                  "allowed_sources": ["synthetic"]}
        policy.update(overrides)
        return policy

    def _report(self, **overrides):
        report = {"schema_version": "1", "run_id": "r", "evaluated_at": "2026-11-12",
                  "model_hash": "a" * 16, "template_hash": "b" * 16, "dataset_hash": "c" * 16,
                  "evaluator_version": "e", "required_checks": ["json_compliance"],
                  "completed_checks": [
                      {"check": "json_compliance", "applicable": True,
                       "sample_ids": ["a", "b"], "sources": ["synthetic"],
                       "evidence_verified_at": "2026-11-10"}],
                  "sample_counts": {"json_compliance": 2}, "findings": [],
                  "metrics": {"runtime_json_compliance": 0.96}}
        report.update(overrides)
        return report

    def test_policy_without_freshness_config_rejected(self):
        policy = self._policy()
        policy.pop("evidence_freshness_days")
        gate = evaluate_release_gate(self._report(), policy)
        self.assertEqual(gate["decision"], "incomplete")
        self.assertIn("策略不符合契约", gate["reasons"][0])

    def test_stale_evidence_incomplete(self):
        gate = evaluate_release_gate(self._report(), self._policy(evidence_freshness_days=1))
        self.assertEqual(gate["decision"], "incomplete")
        self.assertTrue(any("证据过期" in r for r in gate["reasons"]))

    def test_fresh_evidence_passes(self):
        gate = evaluate_release_gate(self._report(), self._policy())
        self.assertEqual(gate["decision"], "pass")

    def test_disallowed_source_incomplete(self):
        report = self._report(completed_checks=[
            {"check": "json_compliance", "applicable": True, "sample_ids": ["a", "b"],
             "sources": ["observed_mixed_unlabeled"], "evidence_verified_at": "2026-11-10"}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")
        self.assertTrue(any("来源" in r for r in gate["reasons"]))


if __name__ == "__main__":
    unittest.main()


class R3GateClosureTests(unittest.TestCase):
    """S1.3 R3 验收：fail-open 闭合——缺来源/缺证据时间/未来日期/清单不一致/
    非有限指标/哈希格式 不再放行；硬失败优先于 incomplete。"""

    def _policy(self, **overrides):
        policy = {"policy_version": "p-r3",
                  "required_checks": ["json_compliance"],
                  "min_samples_per_scenario": {"json_compliance": 2},
                  "metric_thresholds": {"runtime_json_compliance": {"min": 0.95}},
                  "evidence_freshness_days": 7,
                  "allowed_sources": ["synthetic"]}
        policy.update(overrides)
        return policy

    def _report(self, **overrides):
        report = {"schema_version": "1", "run_id": "r", "evaluated_at": "2026-11-16",
                  "model_hash": "a" * 16, "template_hash": "b" * 16,
                  "dataset_hash": "c" * 16, "evaluator_version": "e",
                  "required_checks": ["json_compliance"],
                  "completed_checks": [
                      {"check": "json_compliance", "applicable": True,
                       "sample_ids": ["a", "b"], "sources": ["synthetic"],
                       "evidence_verified_at": "2026-11-14"}],
                  "sample_counts": {"json_compliance": 2}, "findings": [],
                  "metrics": {"runtime_json_compliance": 0.96}}
        report.update(overrides)
        return report

    def test_failing_before_probe_now_incomplete(self):
        # failing-before：本探针曾在 2026-11-16 返回 pass（评审复现）
        report = self._report(completed_checks=[
            {"check": "json_compliance", "applicable": True, "sample_ids": ["a", "b"]}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")
        self.assertTrue(any("数据来源" in r for r in gate["reasons"]))
        self.assertTrue(any("证据核验时间" in r for r in gate["reasons"]))

    def test_missing_sources_incomplete(self):
        report = self._report(completed_checks=[
            {"check": "json_compliance", "applicable": True, "sample_ids": ["a", "b"],
             "evidence_verified_at": "2026-11-14"}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")

    def test_missing_evidence_time_incomplete(self):
        report = self._report(completed_checks=[
            {"check": "json_compliance", "applicable": True, "sample_ids": ["a", "b"],
             "sources": ["synthetic"]}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")

    def test_future_evidence_incomplete(self):
        report = self._report(completed_checks=[
            {"check": "json_compliance", "applicable": True, "sample_ids": ["a", "b"],
             "sources": ["synthetic"], "evidence_verified_at": "2026-11-30"}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")
        self.assertTrue(any("未来日期" in r for r in gate["reasons"]))

    def test_required_checks_mismatch_incomplete(self):
        report = self._report(required_checks=["json_compliance", "extra_claim"])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")
        self.assertTrue(any("不一致" in r for r in gate["reasons"]))

    def test_nonfinite_metric_incomplete(self):
        report = self._report(metrics={"runtime_json_compliance": float("nan")})
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")
        self.assertTrue(any("非有限" in r for r in gate["reasons"]))

    def test_hash_format_incomplete(self):
        report = self._report(model_hash="short")
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "incomplete")

    def test_hard_fail_precedence_over_incomplete_fields(self):
        # 评审验收：隐私外发发现即使报告其他字段不完整也 fail，不被 incomplete 掩盖
        report = self._report(completed_checks=[],   # 必检全未执行
                              findings=[{"type": "privacy_leak", "detail": "x"}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "fail")
        self.assertEqual(gate["counts"]["privacy_leak"], 1)

    def test_override_recommendation_fail_precedence(self):
        report = self._report(completed_checks=[],
                              findings=[{"type": "budget_override_recommendation",
                                         "detail": "x"}])
        gate = evaluate_release_gate(report, self._policy())
        self.assertEqual(gate["decision"], "fail")


class R4CityEvidenceTests(unittest.TestCase):
    """S1.4 R4 验收：缺失/篡改/过期/未登记映射在导航前停止；登记要求可复验证据。"""

    def setUp(self):
        self.mappings = load_city_mappings()
        self.real = self.mappings["mappings"][0]  # 杭州=3（run5真实证据）

    def test_failing_before_missing_evidence_file_now_stops(self):
        # failing-before：证据文件缺失的映射曾返回 ok（评审复现）
        broken = {"mappings": [dict(self.real,
                                     evidence_ref="reports/ghost/evidence.txt")]}
        result = resolve_city_code("杭州", mappings=broken)
        self.assertEqual(result["status"], "needs_city_resolution")
        self.assertIn("证据文件缺失", result["reason"])

    def test_tampered_hash_stops(self):
        broken = {"mappings": [dict(self.real, evidence_hash="f" * 64)]}
        result = resolve_city_code("杭州", mappings=broken)
        self.assertEqual(result["status"], "needs_city_resolution")
        self.assertIn("哈希不匹配", result["reason"])

    def test_content_inconsistency_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            ev = Path(temp) / "ev.txt"
            ev.write_text("该证据文件不含平台码与城市一致性要素", encoding="utf-8")
            broken = {"mappings": [dict(self.real,
                                         evidence_ref="ev.txt",
                                         evidence_hash=__import__("hashlib")
                                         .sha256(ev.read_bytes()).hexdigest())]}
            result = resolve_city_code("杭州", mappings=broken,
                                        base_dir=Path(temp))
            self.assertEqual(result["status"], "needs_city_resolution")
            self.assertIn("一致性", result["reason"])

    def test_future_verified_at_stops(self):
        from datetime import datetime, timezone
        future = datetime(2027, 6, 1, tzinfo=timezone.utc)
        future_mapping = {"mappings": [dict(self.real, verified_at="2027-06-01")]}
        result = resolve_city_code("杭州", mappings=future_mapping, now_utc=future)
        self.assertEqual(result["status"], "needs_city_resolution")
        self.assertIn("未来日期", result["reason"])

    def test_max_age_days_none_is_configuration_error(self):
        with self.assertRaises(ValueError):
            resolve_city_code("杭州", mappings=self.mappings, max_age_days=None)

    def test_registration_requires_existing_and_matching_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            entry = {"city_name": "苏州", "administrative_region": "江苏省苏州市",
                     "platform_city_code": "34", "source_url":
                         "https://www.dianping.com/search/keyword/34/0_%E7%BE%8E%E9%A3%9F",
                     "evidence_ref": "reports/ghost.txt",  # 文件不存在
                     "evidence_hash": "a" * 64, "verified_at": "2026-11-14"}
            with self.assertRaises(CityMappingError):
                register_city_mapping(entry, path=Path(temp) / "m.json",
                                       base_dir=Path(temp))

    def test_registration_rejects_future_date(self):
        with tempfile.TemporaryDirectory() as temp:
            entry = {"city_name": "苏州", "administrative_region": "江苏省苏州市",
                     "platform_city_code": "34",
                     "source_url": "https://www.dianping.com/x",
                     "evidence_ref": "real.txt", "evidence_hash": "a" * 64,
                     "verified_at": "2027-06-01"}
            Path(temp, "real.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(CityMappingError):
                register_city_mapping(entry, path=Path(temp) / "m.json",
                                       base_dir=Path(temp))

    def test_registration_rejects_non_dianping_source_host(self):
        with tempfile.TemporaryDirectory() as temp:
            entry = {"city_name": "苏州", "administrative_region": "江苏省苏州市",
                     "platform_city_code": "34", "source_url": "https://evil.com/x",
                     "evidence_ref": "real.txt", "evidence_hash": "a" * 64,
                     "verified_at": "2026-11-14"}
            Path(temp, "real.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(CityMappingError):
                register_city_mapping(entry, path=Path(temp) / "m.json",
                                       base_dir=Path(temp))

    def test_hangzhou_real_mapping_still_resolves_with_default_policy(self):
        result = resolve_city_code("杭州", mappings=self.mappings)  # 默认90天时效
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["mapping"]["platform_city_code"], "3")


from city_registry import resolve_city_code  # noqa: E402  (置于文件尾以复用既有导入)


if __name__ == "__main__":
    unittest.main()
