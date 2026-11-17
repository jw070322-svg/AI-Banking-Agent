import tempfile
import unittest
from pathlib import Path

from lexicon import LexiconError, extract_keywords, load_lexicon


class LexiconTests(unittest.TestCase):
    def setUp(self):
        self.lexicon = load_lexicon()

    def test_default_loads_with_version(self):
        self.assertTrue(self.lexicon["lexicon_version"].startswith("1111.ver2"))
        self.assertTrue(self.lexicon["categories"])
        self.assertTrue(all(len(p) >= 2 for p in self.lexicon["negation_prefixes"]))

    def test_basic_extraction_matches_historical_rules_order(self):
        keywords, negated, flags = extract_keywords("生日聚餐", self.lexicon)
        self.assertEqual(keywords, ["生日餐厅", "蛋糕", "聚餐餐厅"])
        self.assertEqual(negated, [])
        self.assertEqual(flags, [])

    def test_negation_excludes_keyword_and_flags(self):
        keywords, negated, flags = extract_keywords("生日聚餐 不要蛋糕", self.lexicon)
        self.assertEqual(keywords, ["生日餐厅", "聚餐餐厅"])
        self.assertEqual(negated, ["蛋糕"])
        self.assertTrue(flags)
        # 复核标记不含事件原文
        joined = " ".join(keywords + negated + flags)
        self.assertNotIn("不要蛋糕", joined)

    def test_loose_negation_only_flags(self):
        keywords, negated, flags = extract_keywords("生日聚餐 不要的东西太多", self.lexicon)
        self.assertEqual(keywords, ["生日餐厅", "蛋糕", "聚餐餐厅"])
        self.assertEqual(negated, [])
        self.assertTrue(any("疑似否定" in f for f in flags))

    def test_unknown_event_yields_no_keywords(self):
        keywords, negated, flags = extract_keywords("特殊需求", self.lexicon)
        self.assertEqual((keywords, negated, flags), ([], [], []))

    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(LexiconError):
                load_lexicon(Path(temp) / "nope.json")

    def test_corrupt_json_raises(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(LexiconError):
                load_lexicon(path)

    def test_non_integer_priority_raises(self):
        bad = {"lexicon_version": "v-test", "categories": [
            {"trigger": "生日", "search_keywords": ["生日餐厅"], "priority": "high"}]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text(__import__("json").dumps(bad, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(LexiconError):
                load_lexicon(path)

    def test_single_char_negation_prefix_rejected(self):
        bad = {"lexicon_version": "v-test", "negation_prefixes": ["别"],
               "categories": [{"trigger": "生日", "search_keywords": ["蛋糕"]}]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text(__import__("json").dumps(bad, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(LexiconError):
                load_lexicon(path)


if __name__ == "__main__":
    unittest.main()
