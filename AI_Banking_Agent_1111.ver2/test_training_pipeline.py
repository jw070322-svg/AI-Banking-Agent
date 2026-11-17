"""Phase 4 脚手架测试：轨迹入库（契约+脱敏隔离）、人工审核、防泄漏划分、
仅审板导出、门禁硬断言。全部使用合成数据与临时目录。"""
import json
import tempfile
import unittest
from pathlib import Path

from evaluation.gates import (budget_override_findings, check_gates,
                              privacy_leak_findings)
from schema_check import load_schema, validate
from training_pipeline import (add_trajectory, export_messages, review_trajectory,
                               scan_privacy, split_reviewed, status)

ROOT = Path(__file__).parent


def seed(record_id, **overrides):
    record = {"record_id": record_id, "source_kind": "synthetic", "desensitized": True,
              "review_status": "pending", "model_version": "qwen2.5-0.5b",
              "template_version": "unverified", "page_version": "test",
              "evidence_hashes": [], "customer_ref": "synthetic-cust-1",
              "event_template": "birthday_dinner",
              "input_summary": "合成事件：生日聚餐",
              "model_output": {"service_categories": ["生日餐厅"], "public_keywords": ["生日餐厅"],
                               "constraints": [], "needs_clarification": False,
                               "evidence_spans": ["生日"]}}
    record.update(overrides)
    return record


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def test_add_valid_goes_to_candidate(self):
        result = add_trajectory(seed("t-1"), self.base)
        self.assertEqual(result["status"], "candidate")
        self.assertTrue((self.base / "candidate" / "t-1.json").is_file())

    def test_add_with_pii_goes_to_quarantine(self):
        bad = seed("t-pii", input_summary="合成事件 联系电话13812345678")
        result = add_trajectory(bad, self.base)
        self.assertEqual(result["status"], "quarantined")
        self.assertEqual(result["findings"][0]["kind"], "phone_cn")
        self.assertFalse((self.base / "candidate" / "t-pii.json").exists())

    def test_add_rejects_schema_violation(self):
        bad = seed("t-bad", source_kind="real")  # 枚举外
        with self.assertRaises(ValueError):
            add_trajectory(bad, self.base)

    def test_add_rejects_bad_model_output(self):
        bad = seed("t-mo", model_output={"public_keywords": ["生日餐厅"]})  # 缺字段
        with self.assertRaises(ValueError):
            add_trajectory(bad, self.base)

    def test_review_moves_and_updates(self):
        add_trajectory(seed("t-2"), self.base)
        result = review_trajectory("t-2", "approved", "合成样本审核通过", base_dir=self.base)
        self.assertEqual(result["review_status"], "approved")
        self.assertFalse((self.base / "candidate" / "t-2.json").exists())
        record = json.loads((self.base / "reviewed" / "t-2.json").read_text(encoding="utf-8"))
        self.assertEqual(record["review_status"], "approved")
        self.assertIn("审核", record["notes"])

    def test_review_reject_path(self):
        add_trajectory(seed("t-3"), self.base)
        review_trajectory("t-3", "rejected", "标签错误", base_dir=self.base)
        record = json.loads((self.base / "reviewed" / "t-3.json").read_text(encoding="utf-8"))
        self.assertEqual(record["review_status"], "rejected")

    def test_split_groups_no_leakage(self):
        # 同组两条（同客户×同模板）必须落同一 split
        add_trajectory(seed("g-a", customer_ref="c1", event_template="t1"), self.base)
        add_trajectory(seed("g-b", customer_ref="c1", event_template="t1"), self.base)
        add_trajectory(seed("g-c", customer_ref="c1", event_template="t2"), self.base)
        review_trajectory("g-a", "approved", "ok", base_dir=self.base)
        review_trajectory("g-b", "approved", "ok", base_dir=self.base)
        review_trajectory("g-c", "approved", "ok", base_dir=self.base)
        split_reviewed(self.base)
        a = json.loads((self.base / "reviewed" / "g-a.json").read_text(encoding="utf-8"))
        b = json.loads((self.base / "reviewed" / "g-b.json").read_text(encoding="utf-8"))
        c = json.loads((self.base / "reviewed" / "g-c.json").read_text(encoding="utf-8"))
        self.assertEqual(a["split"], b["split"])  # 同组同划分
        self.assertTrue(all(r["split"] in ("train", "validation", "test")
                            for r in (a, b, c)))

    def test_export_only_approved_train(self):
        add_trajectory(seed("e-1"), self.base)                       # approved+train
        add_trajectory(seed("e-2", customer_ref="c2"), self.base)    # approved+非train组
        add_trajectory(seed("e-3"), self.base)                       # 不审核 → 不导出
        review_trajectory("e-1", "approved", "ok", base_dir=self.base)
        review_trajectory("e-2", "approved", "ok", base_dir=self.base)
        split_reviewed(self.base)
        result = export_messages(self.base)
        self.assertEqual(result["exported"] + result["manifest"]["skipped_not_train"], 2)
        out_file = Path(result["path"])
        lines = [json.loads(l) for l in
                 out_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        for line in lines:
            self.assertEqual(line["messages"][0]["role"], "system")
            self.assertEqual(line["messages"][1]["role"], "user")
            self.assertEqual(line["messages"][2]["role"], "assistant")
            validate(json.loads(line["messages"][2]["content"]),
                     load_schema("qwen_output.schema.json"))
        # e-3 未审核，绝不出现在导出
        self.assertNotIn("e-3", out_file.read_text(encoding="utf-8"))

    def test_scan_privacy_finds_patterns(self):
        self.assertEqual(scan_privacy({"a": "电话13812345678"})[0]["kind"], "phone_cn")
        self.assertIn("id_card_cn", [f["kind"] for f in scan_privacy({"a": "id 11010119900307765X"})])
        self.assertEqual(scan_privacy({"a": "mail a@b.com"})[0]["kind"], "email")
        self.assertEqual(scan_privacy({"a": "干净文本"}), [])


class GateTests(unittest.TestCase):
    def test_privacy_leak_detected(self):
        findings = privacy_leak_findings("搜索 生日聚餐 电话13812345678", "生日聚餐 电话13812345678")
        self.assertTrue(any(f["type"] == "privacy_leak" for f in findings))

    def test_clean_sent_text_passes(self):
        self.assertEqual(privacy_leak_findings("生日餐厅", "生日聚餐 不要蛋糕"), [])

    def test_budget_override_detected(self):
        findings = budget_override_findings(68800, 60000)
        self.assertEqual(len(findings), 1)
        self.assertFalse(check_gates(findings)["pass"])

    def test_gates_pass_only_when_both_zero(self):
        self.assertTrue(check_gates([])["pass"])
        self.assertTrue(check_gates([{"type": "other"}])["pass"])
        combined = budget_override_findings(68800, 60000) + \
            privacy_leak_findings("包含13812345678")
        gates = check_gates(combined)
        self.assertFalse(gates["pass"])
        self.assertEqual(gates["budget_override_count"], 1)
        self.assertEqual(gates["privacy_leak_count"], 1)


class StatusTests(unittest.TestCase):
    def test_status_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            candidate = base / "candidate"
            candidate.mkdir(parents=True)
            for record_id in ("s-1", "s-2"):
                (candidate / f"{record_id}.json").write_text("{}", encoding="utf-8")
            (base / "quarantine").mkdir()
            (base / "quarantine" / "q-1.json").write_text("{}", encoding="utf-8")
            counts = status(base)
            self.assertEqual(counts["candidate"], 2)
            self.assertEqual(counts["quarantine"], 1)
            self.assertEqual(counts["reviewed"], 0)


if __name__ == "__main__":
    unittest.main()
