"""端到端测试：环境生成 -> 契约格式 -> 分析 -> 与标准答案对比。

用固定 seed 和参考日期生成 A~G 七份样例，确保识别结果可复现。
"""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from analysis import evaluate_detection, load_scenario  # noqa: E402
from analysis.evaluate import aggregate_evaluations  # noqa: E402
from make_fixtures import build_all  # noqa: E402


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tempdir = tempfile.TemporaryDirectory()
        cls.paths = build_all(
            seed=42,
            reference_date="2026-10-23",
            out_dir=Path(cls._tempdir.name),
        )

    @classmethod
    def tearDownClass(cls):
        cls._tempdir.cleanup()

    def test_fixtures_cover_all_scenarios(self):
        self.assertEqual(
            [path.stem for path in self.paths],
            [f"SCENARIO_{scenario_type}" for scenario_type in "ABCDEFG"],
        )

    def test_detection_matches_ground_truth(self):
        results = []
        for path in self.paths:
            data = load_scenario(path)
            result = evaluate_detection(data)
            results.append(result)
            with self.subTest(scenario=path.stem):
                self.assertGreaterEqual(
                    result["summary"]["recall"], 0.95,
                    f"{path.stem} 召回率不足：{result['missed']}",
                )
                self.assertGreaterEqual(
                    result["summary"]["precision"], 0.9,
                    f"{path.stem} 精确率不足：{result['false_positives']}",
                )

        aggregate = aggregate_evaluations(results)
        self.assertGreaterEqual(aggregate["summary"]["recall"], 0.95)
        self.assertGreaterEqual(aggregate["summary"]["precision"], 0.9)

    def test_every_expected_type_is_covered(self):
        types = set()
        for path in self.paths:
            data = load_scenario(path)
            for insight in data.get("expected_insights", []):
                types.add(insight["insight_type"])
        self.assertTrue({
            "salary_detected", "duplicate_charge", "failed_transfer",
            "upcoming_bill", "subscription_renewal", "birthday_upcoming",
            "budget_lock",
        } <= types)


if __name__ == "__main__":
    unittest.main()
