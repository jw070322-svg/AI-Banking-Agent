import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent


class CliTests(unittest.TestCase):
    def test_cli_writes_valid_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "reports"
            proc = subprocess.run(
                [sys.executable, str(ROOT / "workflow.py"),
                 str(ROOT / "example_customer.json"), "--output", str(out)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                cwd=str(ROOT))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            handoff_dirs = list(out.iterdir())
            self.assertEqual(len(handoff_dirs), 1)
            plan = json.loads((handoff_dirs[0] / "handoff.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["city"], "杭州")
            self.assertIn("蛋糕", plan["keywords"])
            self.assertFalse(plan["live_executed"])
            self.assertTrue(plan["keyword_source"].startswith("lexicon_"))


if __name__ == "__main__":
    unittest.main()
