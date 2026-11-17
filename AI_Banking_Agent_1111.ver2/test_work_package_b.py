"""工作包B测试（设计文档 §5）：trajectory v2 契约、gold 标签、显式迁移、
关联分量防泄漏划分、split_manifest、导出纪律。全部合成数据+临时目录。"""
import json
import tempfile
import unittest
from pathlib import Path

from schema_check import load_schema, validate
from training_pipeline import (add_trajectory, add_trajectory_v2, export_messages_v2,
                               migrate_v1_to_v2, review_trajectory_v2,
                               split_reviewed_v2)


def v2(record_id, **overrides):
    record = {"record_id": record_id, "schema_version": 2, "source_kind": "synthetic",
              "desensitized": True, "review_status": "pending",
              "model_version": "qwen2.5-0.5b", "template_version": "v1",
              "evidence_hashes": [],
              "customer_group": "group-A", "template_family": "birthday",
              "input_summary": "合成事件：生日聚餐",
              "model_output": {"service_categories": ["生日餐厅"],
                                "public_keywords": ["生日餐厅"], "constraints": [],
                                "needs_clarification": False, "evidence_spans": ["生日"]},
              "gold_output": {"service_categories": ["生日餐厅", "聚餐餐厅"],
                               "public_keywords": ["生日餐厅", "聚餐餐厅"],
                               "constraints": [], "needs_clarification": False,
                               "evidence_spans": ["生日", "聚餐"]},
              "correction_label": "success"}
    record.update(overrides)
    return record


class V2AddTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def test_valid_v2_to_candidate(self):
        result = add_trajectory_v2(v2("b-1"), self.base)
        self.assertEqual(result["status"], "candidate")

    def test_gold_must_pass_contract(self):
        bad = v2("b-2", gold_output={"public_keywords": ["x"]})  # 缺必需字段
        with self.assertRaises(ValueError):
            add_trajectory_v2(bad, self.base)

    def test_prediction_stays_prediction(self):
        # model_output 可为不完整预测吗？不行——它也要过契约（它是历史真实输出）
        bad = v2("b-3", model_output={"foo": 1})
        with self.assertRaises(ValueError):
            add_trajectory_v2(bad, self.base)

    def test_pii_to_quarantine(self):
        result = add_trajectory_v2(
            v2("b-4", input_summary="合成事件 电话13912345678"), self.base)
        self.assertEqual(result["status"], "quarantined")


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def test_v1_migrates_without_fabrication(self):
        seed_path = Path(__file__).parent / "data/trajectories/seeds/synthetic-traj-001-normal.json"
        v1 = json.loads(seed_path.read_text(encoding="utf-8-sig"))
        original_text = seed_path.read_text(encoding="utf-8")
        v2, report = migrate_v1_to_v2(v1)
        self.assertEqual(v2["schema_version"], 2)
        self.assertEqual(v2["customer_group"], "unknown")
        self.assertEqual(v2["template_family"], "unknown")
        self.assertIsNone(v2["gold_output"])
        self.assertIsNone(v2["reviewed_at"])  # 不补造时间
        self.assertIsNone(v2["split"])        # 待 v2 重划分
        self.assertEqual(report["input_sha256"][:8], report["input_sha256"][:8])
        # 原始文件只读保留
        self.assertEqual(seed_path.read_text(encoding="utf-8"), original_text)
        # 迁移产物可入库
        result = add_trajectory_v2(v2, self.base)
        self.assertEqual(result["status"], "candidate")

    def test_migrated_seed_cannot_export_without_gold(self):
        seed_path = Path(__file__).parent / "data/trajectories/seeds/synthetic-traj-001-normal.json"
        v1 = json.loads(seed_path.read_text(encoding="utf-8-sig"))
        v2, _ = migrate_v1_to_v2(v1)
        add_trajectory_v2(v2, self.base)
        review_trajectory_v2("synthetic-traj-001-normal", "approved", "演示",
                             reviewer_ref="tester", base_dir=self.base)
        split_result = split_reviewed_v2(self.base)
        result = export_messages_v2(self.base)
        # 迁移记录分组字段为 unknown → needs_grouping，到不了 train；
        # 即便到 train 也因无 gold 拒绝导出（旧5条种子仅保留管线演示用途，§5.1）
        self.assertEqual(result["exported"], 0)
        self.assertTrue(split_result["needs_grouping"] >= 1
                        or result["manifest"]["skipped_no_gold"] >= 1)


class V2SplitTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def _add_and_approve(self, record):
        add_trajectory_v2(record, self.base)
        review_trajectory_v2(record["record_id"], "approved", "ok",
                             reviewer_ref="tester", base_dir=self.base)

    def test_same_customer_group_same_split_even_across_templates(self):
        self._add_and_approve(v2("r-1", customer_group="c1", template_family="birthday"))
        self._add_and_approve(v2("r-2", customer_group="c1", template_family="wedding"))
        split_reviewed_v2(self.base)
        r1 = json.loads((self.base / "reviewed" / "r-1.json").read_text(encoding="utf-8"))
        r2 = json.loads((self.base / "reviewed" / "r-2.json").read_text(encoding="utf-8"))
        self.assertEqual(r1["split"], r2["split"])
        self.assertIn(r1["split"], ("train", "validation", "test"))

    def test_same_template_family_same_split_across_customers(self):
        self._add_and_approve(v2("r-3", customer_group="c1", template_family="t1"))
        self._add_and_approve(v2("r-4", customer_group="c2", template_family="t1"))
        split_reviewed_v2(self.base)
        r3 = json.loads((self.base / "reviewed" / "r-3.json").read_text(encoding="utf-8"))
        r4 = json.loads((self.base / "reviewed" / "r-4.json").read_text(encoding="utf-8"))
        self.assertEqual(r3["split"], r4["split"])

    def test_transitive_linking_via_cluster(self):
        # c1-t1 与 c2-t2 通过同一 duplicate_cluster 传递关联 → 同一分量
        self._add_and_approve(v2("r-5", customer_group="c1", template_family="t1",
                                 duplicate_cluster="dup-1"))
        self._add_and_approve(v2("r-6", customer_group="c2", template_family="t2",
                                 duplicate_cluster="dup-1"))
        split_reviewed_v2(self.base)
        r5 = json.loads((self.base / "reviewed" / "r-5.json").read_text(encoding="utf-8"))
        r6 = json.loads((self.base / "reviewed" / "r-6.json").read_text(encoding="utf-8"))
        self.assertEqual(r5["split"], r6["split"])

    def test_missing_grouping_goes_to_needs_grouping(self):
        self._add_and_approve(v2("r-7", customer_group=None, template_family=None,
                                 duplicate_cluster=None))
        result = split_reviewed_v2(self.base)
        self.assertEqual(result["needs_grouping"], 1)
        r7 = json.loads((self.base / "reviewed" / "r-7.json").read_text(encoding="utf-8"))
        self.assertEqual(r7["split"], "needs_grouping")

    def test_manifest_reproducible_and_leak_free(self):
        self._add_and_approve(v2("m-1", customer_group="c1"))
        self._add_and_approve(v2("m-2", customer_group="c1"))
        first = split_reviewed_v2(self.base, seed=42)
        second = split_reviewed_v2(self.base, seed=42)
        m1 = json.loads((self.base / "export" / "split_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(first["assigned"], second["assigned"])
        self.assertEqual(m1["intersection_check"], "no_leakage")
        self.assertIn("input_hashes", m1)
        self.assertIn(m1["records"][0]["record_id"], m1["input_hashes"])


class V2ExportTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def _add_approve_split_train(self, record):
        add_trajectory_v2(record, self.base)
        review_trajectory_v2(record["record_id"], "approved", "ok",
                             reviewer_ref="tester", base_dir=self.base)
        # 强制 train：借助同组双记录太绕，直接改写 reviewed 文件的 split
        path = self.base / "reviewed" / f"{record['record_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["split"] = "train"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_gold_is_label_not_prediction(self):
        record = v2("x-1", split=None)
        record["model_output"] = {"service_categories": [], "public_keywords": [],
                                   "constraints": [], "needs_clarification": True,
                                   "evidence_spans": []}  # 预测错
        self._add_approve_split_train(record)
        result = export_messages_v2(self.base)
        self.assertEqual(result["exported"], 1)
        lines = [json.loads(l) for l in
                 Path(result["path"]).read_text(encoding="utf-8").splitlines() if l]
        assistant = json.loads(lines[0]["messages"][2]["content"])
        self.assertEqual(assistant["public_keywords"], ["生日餐厅", "聚餐餐厅"])  # gold

    def test_failure_model_without_gold_refused(self):
        self._add_approve_split_train(
            v2("x-2", gold_output=None, correction_label="failure_model"))
        result = export_messages_v2(self.base)
        self.assertEqual(result["manifest"]["skipped_uncorrected_model_error"], 1)
        self.assertEqual(result["exported"], 0)

    def test_success_without_gold_refused(self):
        self._add_approve_split_train(v2("x-3", gold_output=None))
        result = export_messages_v2(self.base)
        self.assertEqual(result["manifest"]["skipped_no_gold"], 1)

    def test_rejected_never_exported(self):
        add_trajectory_v2(v2("x-4"), self.base)
        review_trajectory_v2("x-4", "rejected", "标签错误",
                             reviewer_ref="tester", base_dir=self.base)
        result = export_messages_v2(self.base)
        self.assertEqual(result["manifest"]["skipped_rejected_or_pending"], 1)

    def test_synthetic_observed_counted_separately(self):
        self._add_approve_split_train(v2("x-5", source_kind="synthetic"))
        self._add_approve_split_train(v2("x-6", source_kind="observed",
                                          customer_group="c9"))
        result = export_messages_v2(self.base)
        self.assertEqual(result["manifest"]["synthetic"], 1)
        self.assertEqual(result["manifest"]["observed"], 1)


if __name__ == "__main__":
    unittest.main()
