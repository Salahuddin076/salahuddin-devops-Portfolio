"""Docs hygiene: required files exist, no stub/TODO markers, no real
identifiers anywhere in the project.
"""

from __future__ import annotations

import re
import unittest

from helpers import DOCS_DIR, PROJECT

STUB_MARKERS = ("TODO", "FIXME", "TBD", "XXX", "lorem ipsum")


class RequiredDocsExistTests(unittest.TestCase):
    def test_readme_exists_and_is_not_empty(self):
        readme = PROJECT / "README.md"
        self.assertTrue(readme.exists())
        self.assertGreater(len(readme.read_text().strip()), 500)

    def test_required_docs_exist(self):
        for name in ("architecture.md", "security.md", "cost.md", "operations.md"):
            self.assertTrue((DOCS_DIR / name).exists(), f"missing docs/{name}")

    def test_decision_records_exist(self):
        decisions = list((DOCS_DIR / "decisions").glob("*.md"))
        self.assertGreaterEqual(len(decisions), 2)


class NoStubMarkersTests(unittest.TestCase):
    def test_no_stub_markers_anywhere_in_markdown(self):
        for md in PROJECT.rglob("*.md"):
            text = md.read_text()
            for marker in STUB_MARKERS:
                self.assertNotIn(marker, text, f"{md} contains stub marker {marker!r}")


class NoRealIdentifiersTests(unittest.TestCase):
    def test_no_real_looking_account_ids_anywhere(self):
        allowed = {"111111111111", "000000000000"}
        pattern = re.compile(r"\b\d{12}\b")
        for path in PROJECT.rglob("*"):
            if not path.is_file() or path.suffix not in (".tf", ".yaml", ".yml", ".md"):
                continue
            if ".terraform" in path.parts:
                continue
            found = set(pattern.findall(path.read_text(errors="ignore")))
            self.assertLessEqual(found, allowed, f"{path} contains a non-placeholder 12-digit id: {found - allowed}")


if __name__ == "__main__":
    unittest.main()
