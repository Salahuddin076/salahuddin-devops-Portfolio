"""Docs stay honest: required docs exist, no stubs, samples are real output."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
import unittest

from helpers import PROJECT

CLASSIFICATION = "Reference implementation — synthetic services, never deployed, no production results claimed."
SAMPLE = re.compile(r"```text\n\$ python3 (scripts/compatibility_check\.py [^\n|]+)\n(.*?)\n```", re.S)
MARKERS = ("TO" + "DO", "FIX" + "ME", "X" * 3 + " ")
SKIP_PARTS = {".terraform", "__pycache__"}


def project_files():
    for p in sorted(PROJECT.rglob("*")):
        if p.is_file() and not SKIP_PARTS.intersection(p.parts):
            yield p


class DocsTests(unittest.TestCase):
    def test_readme_classification(self):
        self.assertIn(CLASSIFICATION, (PROJECT / "README.md").read_text())

    def test_required_docs_exist(self):
        for rel in (
            "docs/architecture.md",
            "docs/operations.md",
            "docs/security.md",
            "docs/cost.md",
            "docs/compatibility-checklist.md",
            "docs/compatibility-manifest.yaml",
            "docs/decisions/0001-native-arm64-build-agents.md",
            "docs/decisions/0002-scheduling-rollback-over-per-arch-tags.md",
            "ci/Jenkinsfile",
        ):
            self.assertTrue((PROJECT / rel).is_file(), rel)
        self.assertGreaterEqual((PROJECT / "docs/architecture.md").read_text().count("```mermaid"), 2)

    def test_scanner_samples_in_readme_are_real_output(self):
        samples = SAMPLE.findall((PROJECT / "README.md").read_text())
        self.assertGreaterEqual(len(samples), 2)
        for cmd, expected in samples:
            with self.subTest(cmd=cmd):
                proc = subprocess.run([sys.executable, *shlex.split(cmd)], cwd=PROJECT, capture_output=True,
                                      text=True, timeout=60, check=False)
                self.assertEqual(f"{proc.stdout.rstrip()}\n(exit {proc.returncode})", expected)

    def test_no_markers_and_no_empty_files(self):
        for p in project_files():
            with self.subTest(path=str(p.relative_to(PROJECT))):
                text = p.read_text(errors="replace")
                self.assertTrue(text.strip(), "empty file")
                for m in MARKERS:
                    self.assertNotIn(m, text)

    def test_placeholder_account_only(self):
        for p in project_files():
            for account in re.findall(r"(?<![\d.])\d{12}(?![\d.])", p.read_text(errors="replace")):
                self.assertEqual(account, "123456789012", p)


if __name__ == "__main__":
    unittest.main()
