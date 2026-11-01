"""main.py 的生成 + 双层校验集成测试。

这些测试回答两个问题：
1. A~F 六类场景都能生成并通过校验；
2. 把任意一类场景的关键语义改坏后，main.validate_scenario 一定能拦住
   （防止"validator 漏规则时错误场景被静默保存"的老问题复发）。
"""

import copy
import unittest

import main


class GenerationTests(unittest.TestCase):
    def setUp(self):
        main.set_seed(42)
        main.set_reference_date("2026-10-23")

    def tearDown(self):
        main.set_seed(None)
        main.set_reference_date(None)

    def build(self, scenario_type):
        config = main.parse_requirement(main.DEFAULT_REQUIREMENTS[scenario_type])
        config["scenario_id"] = f"SCN_TEST_{scenario_type}"
        return config, main.generate_scenario(config)

    def test_all_scenarios_generate_and_pass_validation(self):
        for scenario_type in "ABCDEFG":
            with self.subTest(scenario_type=scenario_type):
                config, scenario = self.build(scenario_type)
                ok, messages = main.validate_scenario(scenario, config)
                self.assertTrue(ok, messages)

    def test_same_seed_reproduces_same_data(self):
        main.set_seed(42)
        _, first = self.build("B")
        main.set_seed(42)  # 重新播种，模拟"换一次运行"
        _, second = self.build("B")
        self.assertEqual(first, second)

    def test_corrupted_duplicate_group_rejected(self):
        config, scenario = self.build("C")
        group = [t for t in scenario["transactions"] if t.get("duplicate_group_id")]
        group[1]["merchant"] = "被改坏的商户"
        ok, messages = main.validate_scenario(scenario, config)
        self.assertFalse(ok)
        self.assertTrue(any("商户不一致" in message for message in messages))

    def test_transfer_within_balance_rejected(self):
        config, scenario = self.build("D")
        rejected = [t for t in scenario["transactions"] if t["status"] == "rejected"][0]
        rejected["amount"] = 1.0
        ok, messages = main.validate_scenario(scenario, config)
        self.assertFalse(ok)
        self.assertTrue(any("未超过可用余额" in message for message in messages))

    def test_changed_subscription_amount_rejected(self):
        config, scenario = self.build("E")
        subscriptions = [t for t in scenario["transactions"] if t.get("category") == "订阅"]
        subscriptions[0]["amount"] = round(subscriptions[0]["amount"] + 5, 2)
        ok, messages = main.validate_scenario(scenario, config)
        self.assertFalse(ok)
        self.assertTrue(any("金额不一致" in message for message in messages))

    def test_birthday_calendar_semantics(self):
        config, scenario = self.build("F")
        birthday = scenario["family"][0]["birthday"]
        self.assertEqual(scenario["budget"]["lock_month"], birthday[:7])
        categories = {
            entry["category"] for entry in scenario["activity_calendar"]
            if entry["date"] == scenario["activity_calendar"][0]["date"]
        }
        self.assertTrue({"鲜花", "蛋糕"} <= categories)

        broken = copy.deepcopy(scenario)
        broken["activity_calendar"] = [
            entry for entry in broken["activity_calendar"] if entry["category"] != "蛋糕"
        ]
        ok, messages = main.validate_scenario(broken, config)
        self.assertFalse(ok)
        self.assertTrue(any("缺少蛋糕" in message for message in messages))

    def test_every_scenario_has_cards_calendar_and_insights(self):
        for scenario_type in "ABCDEFG":
            with self.subTest(scenario_type=scenario_type):
                config, scenario = self.build(scenario_type)
                self.assertEqual(len(scenario["cards"]), 2)
                self.assertTrue(any(card["card_type"] == "credit" for card in scenario["cards"]))
                self.assertTrue(scenario["calendar_events"])
                self.assertTrue(scenario["expected_insights"])
                bill = scenario["credit_card_bill"]
                credit = next(c for c in scenario["cards"] if c["card_type"] == "credit")
                self.assertAlmostEqual(bill["outstanding_amount"], credit["used_credit"], places=2)
                self.assertAlmostEqual(
                    credit["credit_limit"] - credit["used_credit"], credit["available_credit"], places=2
                )

    def test_card_management_scenario_has_events_and_reminder(self):
        config, scenario = self.build("G")
        self.assertTrue(scenario["card_events"])
        self.assertTrue(any(
            event["event_type"] == "bill_due" for event in scenario["calendar_events"]
        ))
        self.assertIn(
            scenario["cards"][1]["status"], {"active", "frozen", "lost", "closed"}
        )

    def test_subscription_scenario_has_next_charge(self):
        config, scenario = self.build("E")
        subscription = scenario["subscriptions"][0]
        self.assertEqual(subscription["status"], "active")
        self.assertRegex(subscription["next_charge_date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertTrue(any(
            event["event_type"] == "subscription_renewal" for event in scenario["calendar_events"]
        ))

    def test_birthday_text_parses_budget(self):
        config = main.parse_requirement("检测我配偶的生日，锁定 1000 元活动预算并生成活动日历")
        self.assertEqual(config["scenario_type"], "F")
        self.assertEqual(config["params"]["monthly_activity_budget"], 1000.0)

    def test_unsupported_business_rejected(self):
        with self.assertRaises(main.ScenarioError):
            main.parse_requirement("帮我做一个房贷场景")


if __name__ == "__main__":
    unittest.main()
