"""Docs stay honest: required sections exist, no stub markers, no real identifiers."""

from __future__ import annotations

import re
import unittest

from helpers import PROJECT

CLASSIFICATION = (
    "Reference architecture -- synthetic, never deployed, no real Azure subscription, "
    "tenant or Azure DevOps organization used."
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
            "docs/decisions/0001-workload-identity-over-service-principal-secrets.md",
            "docs/decisions/0002-separate-state-per-root.md",
        ):
            self.assertTrue((PROJECT / rel).is_file(), rel)
        self.assertGreaterEqual((PROJECT / "docs/architecture.md").read_text().count("```mermaid"), 2)

    def test_no_markers_and_no_empty_files(self):
        for p in project_files():
            with self.subTest(path=str(p.relative_to(PROJECT))):
                text = p.read_text(errors="replace")
                self.assertTrue(text.strip(), "empty file")
                for m in MARKERS:
                    self.assertNotIn(m, text)

    def test_no_real_tenant_or_subscription_ids(self):
        # Every GUID-shaped value in the repo should be one of the documented
        # synthetic placeholders (all-same-digit GUIDs), never anything else.
        synthetic_guids = {
            "00000000-0000-0000-0000-000000000000",
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
            "33333333-3333-3333-3333-333333333333",
            "44444444-4444-4444-4444-444444444444",
        }
        guid_re = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
        for p in project_files():
            text = p.read_text(errors="replace")
            for match in guid_re.findall(text):
                with self.subTest(path=str(p.relative_to(PROJECT)), guid=match):
                    self.assertIn(match, synthetic_guids)


if __name__ == "__main__":
    unittest.main()
