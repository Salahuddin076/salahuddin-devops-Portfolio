import subprocess
import sys
import unittest

from helpers import PROJECT_DIR


class LocalDemoTests(unittest.TestCase):
    def run_demo(self, *args):
        return subprocess.run(
            [sys.executable, str(PROJECT_DIR / "scripts" / "local_demo.py"), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_demo_runs_and_shows_each_path(self):
        result = self.run_demo()
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn("client retry, same key           -> 202", out)
        self.assertIn("missing Idempotency-Key          -> 400  Idempotency-Key: header is required", out)
        self.assertIn("duplicate  skipped, stored result", out)
        self.assertIn("redrive policy: ['msg-0004'] moved to DLQ after 3 receives", out)
        self.assertIn("events published: 2   duplicates skipped: 1", out)

    def test_demo_is_deterministic(self):
        self.assertEqual(self.run_demo().stdout, self.run_demo().stdout)

    def test_show_logs_prints_json(self):
        result = self.run_demo("--show-logs")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"message":"poison_message"', result.stdout)


if __name__ == "__main__":
    unittest.main()
