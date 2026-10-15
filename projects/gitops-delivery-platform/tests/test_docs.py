"""Docs stay honest: the README's samples are real output, labels are right, no stubs or client names."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
import unittest

from helpers import PROJECT

CLASSIFICATION = ("Reference implementation of a pattern used in production work; all names and values are "
                  "synthetic. No production figures are claimed.")
SAMPLE = re.compile(r"(?m)^(`{3,4})text\n\$ python3 (scripts/(?:promote|drift_report|check_gitops_policy)\.py"
                    r"[^\n|]*)\n(.*?)\n\1$", re.S)
MARKERS = ("TO" + "DO", "FIX" + "ME", "X" * 3 + " ")
FORBIDDEN = re.compile(r"\b(" + "auto" + "leap" + "|" + "a" + "lp" + r")\b", re.I)
SKIP_PARTS = {"__pycache__"}


def project_files():
    for p in sorted(PROJECT.rglob("*")):
        if p.is_file() and not SKIP_PARTS.intersection(p.parts):
            yield p


class DocsTests(unittest.TestCase):
    def test_readme_classification(self):
        readme = (PROJECT / "README.md").read_text()
        self.assertIn(CLASSIFICATION, readme)
        self.assertIn("production case study", readme)

    def test_required_docs_exist(self):
        for rel in ("docs/architecture.md", "docs/operations.md", "docs/security.md", "docs/cost.md",
                    "docs/decisions/0001-pull-based-gitops.md", "docs/decisions/0002-two-repo-split.md",
                    "docs/decisions/0003-external-secrets-vs-sealed-secrets.md",
                    "docs/decisions/0004-argo-rollouts-canary-for-prod.md",
                    "app-repo/README.md", "config-repo/README.md", ".gitignore"):
            self.assertTrue((PROJECT / rel).is_file(), rel)
        self.assertGreaterEqual((PROJECT / "docs/architecture.md").read_text().count("```mermaid"), 5)

    def test_samples_in_readme_are_real_output(self):
        samples = SAMPLE.findall((PROJECT / "README.md").read_text())
        self.assertGreaterEqual(len(samples), 5)
        for _fence, cmd, expected in samples:
            with self.subTest(cmd=cmd):
                proc = subprocess.run([sys.executable, *shlex.split(cmd)], cwd=PROJECT, capture_output=True,
                                      text=True, timeout=60, check=False)
                self.assertEqual(f"{proc.stdout.rstrip()}\n(exit {proc.returncode})", expected)

    def test_operations_cover_the_runbook_topics(self):
        ops = (PROJECT / "docs/operations.md").read_text()
        for heading in ("## Bootstrapping Argo CD", "## Promoting", "## Emergency hotfix", "## Rollback",
                        "## Handling drift", "## Sync windows"):
            self.assertIn(heading, ops)
        self.assertIn("--version 10.10.3", ops)
        self.assertIn("argo rollouts abort", ops)
        self.assertIn("git revert", ops)
        self.assertIn("Pod Identity", (PROJECT / "docs/security.md").read_text())
        self.assertIn("illustrative", (PROJECT / "docs/cost.md").read_text())

    def test_no_markers_and_no_empty_files(self):
        for p in project_files():
            with self.subTest(path=str(p.relative_to(PROJECT))):
                text = p.read_text(errors="replace")
                self.assertTrue(text.strip(), "empty file")
                for m in MARKERS:
                    self.assertNotIn(m, text)

    def test_placeholders_only_and_no_client_names(self):
        for p in project_files():
            text = p.read_text(errors="replace")
            for account in re.findall(r"(?<![\da-f.-])\d{12}(?![\da-f.-])", text):
                self.assertEqual(account, "123456789012", p)
            self.assertIsNone(FORBIDDEN.search(text), p)
            for host in re.findall(r"https?://([a-z0-9.-]+)", text):
                with self.subTest(path=str(p.relative_to(PROJECT)), host=host):
                    self.assertTrue(host.endswith(("example.com", "github.com", "githubusercontent.com",
                                                   "kubernetes.default.svc", "monitoring.svc", "helm.sh",
                                                   "argoproj.github.io", "external-secrets.io", "json-schema.org",
                                                   "127.0.0.1")) or host in ("charts.external-secrets.io",),
                                    host)

    def test_no_plaintext_secret_manifests(self):
        for p in (PROJECT / "config-repo").rglob("*.yaml"):
            self.assertNotRegex(p.read_text(), r"(?m)^kind: Secret$", p)


if __name__ == "__main__":
    unittest.main()
