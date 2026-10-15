"""CLI smoke tests: slogen subcommands and the demo app, as subprocesses."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import GENERATED, PROJECT, SAMPLE_CSV


def run(*args):
    return subprocess.run([sys.executable, "generator/slogen.py", *map(str, args)], cwd=PROJECT,
                          capture_output=True, text=True, timeout=60, check=False)


class SlogenCliTests(unittest.TestCase):
    def test_generate_check_is_clean(self):
        proc = run("generate", "--check")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("slogen: 12 files, up to date", proc.stdout)
        self.assertIn("checkout-api: 2 SLO(s), 22 recording rules, 8 alerts, 1 dashboard", proc.stdout)

    def test_generate_into_temp_then_check_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "gen"
            self.assertEqual(run("generate", "--out", out).returncode, 0)
            self.assertEqual(sorted(p.name for p in out.rglob("*") if p.is_file()),
                             sorted(p.name for p in GENERATED.rglob("*") if p.is_file()))
            (out / "prometheus" / "meta.rules.yml").write_text("x\n")
            proc = run("generate", "--out", out, "--check")
            self.assertEqual(proc.returncode, 1)
            self.assertIn("changed: prometheus/meta.rules.yml", proc.stdout)

    def test_explain(self):
        proc = run("explain")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("page-1h   page   burn >14.4x over 1h and  5m: error ratio > 1.44%, 2% of budget per 1h, empty in 2.1d",
                      proc.stdout)

    def test_report_text_and_json(self):
        text = run("report", SAMPLE_CSV.relative_to(PROJECT), "--slo", "slo/checkout-api.json", "--name", "availability")
        self.assertEqual(text.returncode, 0, text.stderr)
        self.assertEqual(text.stdout, (GENERATED / "reports" / "checkout-api-availability.txt").read_text())
        js = run("report", SAMPLE_CSV, "--slo", "slo/checkout-api.json", "--name", "availability", "--format", "json")
        data = json.loads(js.stdout)
        self.assertEqual(data["alerts"][0]["fired"], "2026-09-03T13:00:00Z")
        self.assertEqual(data["errors"], 2194)

    def test_errors_exit_2(self):
        proc = run("report", SAMPLE_CSV, "--slo", "slo/checkout-api.json", "--name", "nope")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no SLO named", proc.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run("generate", "--slo-dir", tmp, "--check").returncode, 2)
        self.assertEqual(run("report", "missing.csv", "--slo", "slo/checkout-api.json", "--name", "latency").returncode, 2)


class DemoAppCliTests(unittest.TestCase):
    def test_help(self):
        proc = subprocess.run([sys.executable, "local/demo-app/demo_app.py", "--help"], cwd=PROJECT,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--port", proc.stdout)


if __name__ == "__main__":
    unittest.main()
