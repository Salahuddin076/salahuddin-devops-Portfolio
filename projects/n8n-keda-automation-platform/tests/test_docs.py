"""Docs stay honest: the README's samples are real output, labels are right, no stubs or client names."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
import unittest

from helpers import PROJECT

CLASSIFICATION = ("Reference implementation of a pattern used in production work; all names, accounts and "
                  "values are synthetic. No production figures are claimed.")
SAMPLE = re.compile(r"```text\n\$ python3 (scripts/(?:keda_scaling_sim|check_chart_policy|duplicate_job_guard)\.py "
                    r"[^\n|]+)\n(.*?)\n```", re.S)
MARKERS = ("TO" + "DO", "FIX" + "ME", "X" * 3 + " ")
FORBIDDEN = re.compile(r"\b(" + "auto" + "leap" + "|" + "a" + "lp" + r")\b", re.I)
SKIP_PARTS = {".terraform", "__pycache__"}


def project_files():
    for p in sorted(PROJECT.rglob("*")):
        if p.is_file() and not SKIP_PARTS.intersection(p.parts):
            yield p


class DocsTests(unittest.TestCase):
    def test_readme_classification(self):
        self.assertIn(CLASSIFICATION, (PROJECT / "README.md").read_text())

    def test_required_docs_exist(self):
        for rel in ("docs/architecture.md", "docs/operations.md", "docs/security.md", "docs/cost.md",
                    "docs/decisions/0001-queue-mode.md",
                    "docs/decisions/0002-keda-redis-list-scaler-vs-cpu-hpa.md",
                    "docs/decisions/0003-trigger-authentication-secrets.md",
                    "docs/decisions/0004-database-choice.md"):
            self.assertTrue((PROJECT / rel).is_file(), rel)
        self.assertGreaterEqual((PROJECT / "docs/architecture.md").read_text().count("```mermaid"), 3)

    def test_samples_in_readme_are_real_output(self):
        samples = SAMPLE.findall((PROJECT / "README.md").read_text())
        self.assertGreaterEqual(len(samples), 4)
        for cmd, expected in samples:
            with self.subTest(cmd=cmd):
                proc = subprocess.run([sys.executable, *shlex.split(cmd)], cwd=PROJECT, capture_output=True,
                                      text=True, timeout=60, check=False)
                self.assertEqual(f"{proc.stdout.rstrip()}\n(exit {proc.returncode})", expected)

    def test_simulator_disclaimer_in_docs(self):
        readme = (PROJECT / "README.md").read_text()
        self.assertIn("not KEDA itself", readme)
        self.assertIn("model of documented", (PROJECT / "docs/architecture.md").read_text())

    def test_no_markers_and_no_empty_files(self):
        for p in project_files():
            with self.subTest(path=str(p.relative_to(PROJECT))):
                text = p.read_text(errors="replace")
                self.assertTrue(text.strip(), "empty file")
                for m in MARKERS:
                    self.assertNotIn(m, text)

    def test_placeholder_account_and_no_client_names(self):
        for p in project_files():
            text = p.read_text(errors="replace")
            for account in re.findall(r"(?<![\d.])\d{12}(?![\d.])", text):
                self.assertEqual(account, "123456789012", p)
            self.assertIsNone(FORBIDDEN.search(text), p)


if __name__ == "__main__":
    unittest.main()
