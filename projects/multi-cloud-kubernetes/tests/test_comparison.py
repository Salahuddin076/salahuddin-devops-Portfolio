"""Tests for docs/comparison.yaml and scripts/render_comparison.py: the
comparison doc must stay complete (every dimension has a value for every
cloud) and the renderer must catch it if it ever doesn't.
"""

from __future__ import annotations

import unittest

from helpers import DOCS_DIR

import render_comparison

COMPARISON_PATH = DOCS_DIR / "comparison.yaml"


class LoadComparisonTests(unittest.TestCase):
    def test_live_comparison_doc_loads_and_validates(self):
        data = render_comparison.load_comparison(COMPARISON_PATH)
        self.assertGreaterEqual(len(data["clouds"]), 3)
        self.assertGreaterEqual(len(data["dimensions"]), 5)

    def test_covers_eks_aks_and_gke(self):
        data = render_comparison.load_comparison(COMPARISON_PATH)
        cloud_ids = {c["id"] for c in data["clouds"]}
        self.assertEqual(cloud_ids, {"eks", "aks", "gke"})

    def test_every_dimension_has_a_value_for_every_cloud(self):
        data = render_comparison.load_comparison(COMPARISON_PATH)
        cloud_ids = [c["id"] for c in data["clouds"]]
        for dim in data["dimensions"]:
            for cid in cloud_ids:
                self.assertIn(cid, dim["values"], f"{dim['id']} missing a value for {cid}")
                self.assertTrue(dim["values"][cid].strip(), f"{dim['id']} has an empty value for {cid}")

    def test_every_dimension_has_a_note(self):
        data = render_comparison.load_comparison(COMPARISON_PATH)
        for dim in data["dimensions"]:
            self.assertTrue(dim.get("note", "").strip(), f"{dim['id']} is missing its note")


class ValidationCatchesIncompleteDataTests(unittest.TestCase):
    def test_missing_cloud_value_raises(self):
        data = {
            "clouds": [{"id": "eks", "name": "EKS"}, {"id": "aks", "name": "AKS"}],
            "dimensions": [{"id": "x", "label": "X", "values": {"eks": "a"}}],
        }
        with self.assertRaises(ValueError):
            render_comparison.validate(data)

    def test_duplicate_cloud_id_raises(self):
        data = {
            "clouds": [{"id": "eks", "name": "EKS"}, {"id": "eks", "name": "EKS again"}],
            "dimensions": [{"id": "x", "label": "X", "values": {"eks": "a"}}],
        }
        with self.assertRaises(ValueError):
            render_comparison.validate(data)

    def test_no_dimensions_raises(self):
        data = {"clouds": [{"id": "eks", "name": "EKS"}, {"id": "aks", "name": "AKS"}], "dimensions": []}
        with self.assertRaises(ValueError):
            render_comparison.validate(data)

    def test_complete_data_does_not_raise(self):
        data = {
            "clouds": [{"id": "eks", "name": "EKS"}, {"id": "aks", "name": "AKS"}],
            "dimensions": [{"id": "x", "label": "X", "values": {"eks": "a", "aks": "b"}}],
        }
        render_comparison.validate(data)  # should not raise


class RenderMarkdownTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "clouds": [{"id": "eks", "name": "EKS"}, {"id": "aks", "name": "AKS"}],
            "dimensions": [{"id": "x", "label": "Dimension X", "values": {"eks": "e-value", "aks": "a-value"}}],
        }

    def test_renders_a_markdown_table_header(self):
        out = render_comparison.render_markdown(self.data)
        self.assertIn("| Dimension | EKS | AKS |", out)

    def test_renders_each_dimension_row(self):
        out = render_comparison.render_markdown(self.data)
        self.assertIn("Dimension X", out)
        self.assertIn("e-value", out)
        self.assertIn("a-value", out)

    def test_cli_main_returns_zero_on_the_live_doc(self):
        self.assertEqual(render_comparison.main(["render_comparison.py", str(COMPARISON_PATH)]), 0)

    def test_cli_main_returns_one_on_invalid_data(self, ):
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("clouds:\n  - id: eks\n    name: EKS\ndimensions: []\n")
            path = f.name
        try:
            self.assertEqual(render_comparison.main(["render_comparison.py", path]), 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
