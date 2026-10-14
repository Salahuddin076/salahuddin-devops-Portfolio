"""The rotation drill, for real: the app in a subprocess, files swapped like the CSI driver does."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import SCRIPTS_DIR

import secret_rotation_drill as drill


class AtomicWriterTests(unittest.TestCase):
    def test_layout_matches_the_driver_and_swap_is_one_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "s"
            drill.write_version(d, {"a": "1", "b": "2"})
            first = os.readlink(d / "..data")
            self.assertTrue((d / "a").is_symlink())
            self.assertEqual(os.readlink(d / "a"), os.path.join("..data", "a"))
            drill.write_version(d, {"a": "3", "b": "4"})
            self.assertNotEqual(os.readlink(d / "..data"), first)
            self.assertFalse((d / first).exists(), "old version directory is cleaned up")
            self.assertEqual(((d / "a").read_text(), (d / "b").read_text()), ("3", "4"))
            self.assertFalse((d / "..data_tmp").exists())


class DrillTests(unittest.TestCase):
    def test_drill_observes_rotation_and_prints_no_values(self):
        out = io.StringIO()
        result = drill.run_drill(timeout=10, app_poll=0.2, check_every=0.05, out=out)
        text = out.getvalue()
        self.assertTrue(result.ok, text)
        self.assertEqual(result.exit_code, 0)
        self.assertLess(result.observed_after, 5)
        self.assertIn("app observed v2", text)
        self.assertIn("log check: 0 of 8 secret values", text)
        self.assertRegex(text, r"PASS rotation observed \d+\.\d{3}s after the swap")
        self.assertEqual(len(result.values), 8)
        for value in result.values:
            self.assertNotIn(value, text)
        self.assertIn("secrets rotated", result.app_log)

    def test_drill_fails_when_the_app_does_not_pick_up_v2_in_time(self):
        # App polls every 30 s, the drill waits 1 s: rotation is not observed.
        proc = subprocess.run([sys.executable, str(SCRIPTS_DIR / "secret_rotation_drill.py"),
                               "--timeout", "1", "--app-poll", "30"],
                              capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("FAIL v2 not observed within 1.0s", proc.stdout)

    def test_cli_passes(self):
        proc = subprocess.run([sys.executable, str(SCRIPTS_DIR / "secret_rotation_drill.py"),
                               "--timeout", "10", "--app-poll", "0.2"],
                              capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS", proc.stdout)


if __name__ == "__main__":
    unittest.main()
