"""Docs stay honest: required sections exist, no stub markers, no real identifiers."""

from __future__ import annotations

import re
import unittest

from helpers import PROJECT

CLASSIFICATION = (
    "Working portfolio implementation — synthetic reference implementation of a "
    "real pattern, never deployed, no real GCP project or account used."
)
MARKERS = ("TO" + "DO", "FIX" + "ME", "X" * 3 + " ")
SKIP_PARTS = {".terraform", "__pycache__", "charts"}
REQUIRED_README_SECTIONS = (
    "## Problem",
    "## Solution",
    "## Architecture",
    "## Security",
    "## Reliability",
    "## Cost",
    "## Results",
    "## Limitations",
    "## Lessons",
)


def project_files():
    for p in sorted(PROJECT.rglob("*")):
        if p.is_file() and not SKIP_PARTS.intersection(p.parts):
            yield p


class ReadmeTests(unittest.TestCase):
    def setUp(self):
        self.readme = (PROJECT / "README.md").read_text()

    def test_readme_classification(self):
        self.assertIn(CLASSIFICATION, self.readme)

    def test_readme_has_every_required_section(self):
        for heading in REQUIRED_README_SECTIONS:
            with self.subTest(heading=heading):
                self.assertIn(heading, self.readme)

    def test_cost_and_results_sections_say_illustrative(self):
        cost_idx = self.readme.index("## Cost")
        results_idx = self.readme.index("## Results")
        limitations_idx = self.readme.index("## Limitations")
        self.assertIn("illustrative", self.readme[cost_idx:results_idx].lower())
        self.assertIn("illustrative", self.readme[results_idx:limitations_idx].lower())

    def test_required_docs_exist(self):
        for rel in (
            "docs/architecture.md",
            "docs/security.md",
            "docs/cost.md",
            "docs/operations.md",
            "docs/decisions/0001-workload-identity-over-key-files.md",
            "docs/decisions/0002-separate-state-per-layer.md",
            "docs/decisions/0003-separate-node-pools-for-api-and-ai.md",
        ):
            self.assertTrue((PROJECT / rel).is_file(), rel)
        self.assertGreaterEqual((PROJECT / "docs/architecture.md").read_text().count("```mermaid"), 3)

    def test_no_markers_and_no_empty_files(self):
        for p in project_files():
            with self.subTest(path=str(p.relative_to(PROJECT))):
                text = p.read_text(errors="replace")
                self.assertTrue(text.strip(), "empty file")
                for m in MARKERS:
                    self.assertNotIn(m, text)

    def test_no_real_project_ids_or_credentials(self):
        # Only the documented synthetic project ID should ever appear.
        for p in project_files():
            text = p.read_text(errors="replace")
            for match in re.findall(r"[a-z][a-z0-9-]{4,28}\.iam\.gserviceaccount\.com", text):
                self.assertIn("example-pharmacy-platform", match, p)
            self.assertNotRegex(text, r"(?i)AIza[0-9A-Za-z_-]{30,}")  # a real-looking Google API key


if __name__ == "__main__":
    unittest.main()
