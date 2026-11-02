"""扰动样例测试：确保已知误报点不会复发。"""

import unittest

from perturbations import build_cases, run_cases


class PerturbationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_cases()

    def test_all_cases_pass(self):
        failed = [row["name"] for row in self.result["cases"] if not row["passed"]]
        self.assertEqual(failed, [], f"以下扰动样例未通过：{failed}")

    def test_no_false_positives(self):
        self.assertEqual(self.result["summary"]["fp"], 0)
        self.assertEqual(self.result["summary"]["fn"], 0)

    def test_same_store_same_amount_hours_apart_is_not_duplicate(self):
        row = next(
            row for row in self.result["cases"]
            if row["name"] == "正常消费_同店同额相隔半天"
        )
        self.assertEqual(row["detected"], 0)
        self.assertTrue(row["passed"])

    def test_recurring_rent_is_not_unusual(self):
        row = next(
            row for row in self.result["cases"]
            if row["name"] == "异常消费_大额但符合平均"
        )
        self.assertEqual(row["detected"], 0)

    def test_small_subscription_change_is_ignored(self):
        row = next(
            row for row in self.result["cases"]
            if row["name"] == "订阅调价_只有1元波动"
        )
        self.assertEqual(row["detected"], 0)

    def test_cases_are_deterministic(self):
        second = run_cases()
        self.assertEqual(
            [(row["name"], row["detected"], row["passed"]) for row in self.result["cases"]],
            [(row["name"], row["detected"], row["passed"]) for row in second["cases"]],
        )

    def test_case_builders_do_not_share_state(self):
        first = build_cases()
        second = build_cases()
        self.assertEqual(len(first), len(second))
        self.assertEqual(first[0]["scenario"], second[0]["scenario"])


if __name__ == "__main__":
    unittest.main()
