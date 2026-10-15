"""Docs stay honest: README samples are real output, labels are right, runbooks exist, no stubs or client names."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
import unittest

from helpers import PROJECT, SLO_DIR

import slogen

CLASSIFICATION = ("Reference implementation of a pattern used in production work; services, SLOs and data are "
                  "synthetic. No production figures are claimed.")
SAMPLE = re.compile(r"```text\n\$ python3 (generator/slogen\.py [^\n|]+)\n(.*?)\n```", re.S)
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
        self.assertIn("**Classification: production case study.**", readme)

    def test_required_docs_exist(self):
        for rel in ("docs/architecture.md", "docs/operations.md", "docs/security.md", "docs/cost.md",
                    "docs/decisions/0001-multiwindow-multiburn-alerts.md",
                    "docs/decisions/0002-slo-as-code-generator-vs-sloth-pyrra.md",
                    "docs/decisions/0003-otel-collector-pii-scrubbing.md",
                    "runbooks/error-budget-policy.md", "runbooks/incident-response.md", "runbooks/watchdog.md"):
            self.assertTrue((PROJECT / rel).is_file(), rel)
        self.assertGreaterEqual((PROJECT / "docs/architecture.md").read_text().count("```mermaid"), 3)
        self.assertIn("illustrative", (PROJECT / "docs/cost.md").read_text().lower())

    def test_every_runbook_url_has_a_runbook(self):
        urls = {slogen.meta_rules()["groups"][0]["rules"][0]["annotations"]["runbook_url"]}
        for svc in slogen.load_all(SLO_DIR):
            for g in slogen.service_rules(svc)["groups"]:
                urls |= {r["annotations"]["runbook_url"] for r in g["rules"] if "alert" in r}
        self.assertEqual(len(urls), 9)
        for url in urls:
            self.assertTrue(url.startswith(slogen.RUNBOOK_BASE), url)
            path = PROJECT / "runbooks" / url[len(slogen.RUNBOOK_BASE):]
            self.assertTrue(path.is_file(), path)

    def test_policy_and_incident_docs_cover_the_brief(self):
        policy = (PROJECT / "runbooks/error-budget-policy.md").read_text().lower()
        for word in ("feature freeze", "exceptions", "review cadence"):
            self.assertIn(word, policy)
        incident = (PROJECT / "runbooks/incident-response.md").read_text().lower()
        for word in ("severity", "roles", "communications template", "postmortem template", "blameless"):
            self.assertIn(word, incident)

    def test_samples_in_readme_are_real_output(self):
        samples = SAMPLE.findall((PROJECT / "README.md").read_text())
        self.assertEqual(len(samples), 3)
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

    def test_no_client_names_or_account_ids(self):
        for p in project_files():
            text = p.read_text(errors="replace")
            self.assertIsNone(FORBIDDEN.search(text), p)
            self.assertIsNone(re.search(r"(?<![\d.])\d{12}(?![\d.])", text), p)

    def test_pinned_images(self):
        compose = (PROJECT / "docker-compose.yml").read_text()
        images = re.findall(r"image:\s*(\S+)", compose)
        self.assertEqual(len(images), 4)
        for image in images:
            self.assertRegex(image, r":v?\d+\.\d+\.\d+", image)
            self.assertNotIn("latest", image)


if __name__ == "__main__":
    unittest.main()
