"""主任务与环境生成 Agent 的桥接测试。"""

import unittest

from bridge import (
    environment_status,
    generate_all,
    generate_scenario,
    reset_generation_cache,
)


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset_generation_cache()

    def test_environment_is_available(self):
        status = environment_status()
        self.assertTrue(status["available"], status)
        self.assertEqual(status["scenario_types"], list("ABCDEFG"))
        self.assertIn("A", status["scenario_names"])

    def test_generate_contract_scenario(self):
        scenario = generate_scenario(
            "生成一个疑似重复扣款场景",
            scenario_type="C",
            seed=42,
            reference_date="2026-10-23",
        )
        self.assertEqual(scenario["scenario_type"], "C")
        self.assertEqual(scenario["currency"], "CNY")
        self.assertFalse(scenario["ledger_modified"])
        self.assertTrue(scenario["transactions"])
        sample = scenario["transactions"][0]
        self.assertIsInstance(sample["amount_minor"], int)
        self.assertIn("direction", sample)
        self.assertEqual(sample["status"], "booked")
        self.assertTrue(scenario["expected_insights"])
        # 不包含原始个人信息
        self.assertNotIn("id_number", scenario["user"])
        self.assertNotIn("phone", scenario["user"])

    def test_same_seed_is_reproducible(self):
        first = generate_scenario(
            "疑似重复扣款", scenario_type="C", seed=7, reference_date="2026-10-23"
        )
        second = generate_scenario(
            "疑似重复扣款", scenario_type="C", seed=7, reference_date="2026-10-23"
        )
        self.assertEqual(first["scenario_id"], second["scenario_id"])
        self.assertEqual(
            [t["transaction_id"] for t in first["transactions"]],
            [t["transaction_id"] for t in second["transactions"]],
        )

    def test_generate_all_scenarios(self):
        scenarios = generate_all(seed=42, reference_date="2026-10-23")
        self.assertEqual(sorted(scenarios), list("ABCDEFG"))
        for scenario_type, scenario in scenarios.items():
            with self.subTest(scenario_type=scenario_type):
                self.assertEqual(scenario["scenario_type"], scenario_type)
                self.assertTrue(scenario["cards"])
                self.assertTrue(scenario["calendar_events"])


if __name__ == "__main__":
    unittest.main()
