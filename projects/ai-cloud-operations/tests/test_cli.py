from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class CliSmokeTests(unittest.TestCase):
    def test_generate_then_run_then_approve_then_audit(self):
        with tempfile.TemporaryDirectory() as workdir:
            data_dir = Path(workdir) / "sample-data"
            out_dir = Path(workdir) / "out"

            gen = subprocess.run(
                [sys.executable, "-m", "aiops", "generate", "--out", str(data_dir)],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(gen.returncode, 0, gen.stderr)

            run_res = subprocess.run(
                [sys.executable, "-m", "aiops", "run", "--input", str(data_dir),
                 "--out", str(out_dir), "--format", "json"],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(run_res.returncode, 0, run_res.stderr)
            payload = json.loads(run_res.stdout)
            self.assertEqual(len(payload["items"]), 1)
            proposal_id = payload["items"][0]["proposal"]["id"]

            approve_res = subprocess.run(
                [sys.executable, "-m", "aiops", "approve", "--out", str(out_dir),
                 "--id", proposal_id, "--actor", "oncall@example.com"],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(approve_res.returncode, 0, approve_res.stderr)

            audit_res = subprocess.run(
                [sys.executable, "-m", "aiops", "audit", "--out", str(out_dir)],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(audit_res.returncode, 0, audit_res.stderr)
            self.assertIn("proposed", audit_res.stdout)
            self.assertIn("approved", audit_res.stdout)
            self.assertIn("oncall@example.com", audit_res.stdout)

            audit_lines = (out_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(audit_lines), 2)
            for line in audit_lines:
                json.loads(line)

    def test_approve_unknown_id_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as workdir:
            out_dir = Path(workdir) / "out"
            out_dir.mkdir()
            (out_dir / "proposals.json").write_text("[]", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "aiops", "approve", "--out", str(out_dir),
                 "--id", "doesnotexist", "--actor", "a"],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("error", result.stderr)

    def test_run_with_no_anomalies_exits_zero(self):
        with tempfile.TemporaryDirectory() as workdir:
            data_dir = Path(workdir) / "sample-data"
            data_dir.mkdir()
            (data_dir / "logs.jsonl").write_text(
                '{"timestamp": "2026-01-01T00:00:00Z", "service": "a", "level": "INFO", "message": "ok"}\n',
                encoding="utf-8",
            )
            (data_dir / "deploys.jsonl").write_text("", encoding="utf-8")
            (data_dir / "alerts.jsonl").write_text("", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "aiops", "run", "--input", str(data_dir),
                 "--out", str(Path(workdir) / "out")],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("No anomalies detected", result.stdout)


if __name__ == "__main__":
    unittest.main()
