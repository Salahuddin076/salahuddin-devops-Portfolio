"""Static assertions over argocd/: one ApplicationSet should deploy the one
chart to all three clusters, each with its own values overlay -- the "one
deployment model" this project is named for.
"""

from __future__ import annotations

import unittest

from helpers import ARGOCD_DIR

import yaml_lite


def _load_all(path):
    return [doc for doc in yaml_lite.load_all(path.read_text()) if doc]


class ApplicationSetTests(unittest.TestCase):
    def setUp(self):
        docs = _load_all(ARGOCD_DIR / "applicationset.yaml")
        self.assertEqual(len(docs), 1)
        self.appset = docs[0]

    def test_is_an_applicationset(self):
        self.assertEqual(self.appset["kind"], "ApplicationSet")

    def test_list_generator_has_exactly_three_clouds(self):
        elements = self.appset["spec"]["generators"][0]["list"]["elements"]
        clouds = {e["cloud"] for e in elements}
        self.assertEqual(clouds, {"eks", "aks", "gke"})

    def test_each_element_points_at_a_distinct_values_file(self):
        elements = self.appset["spec"]["generators"][0]["list"]["elements"]
        values_files = {e["valuesFile"] for e in elements}
        self.assertEqual(values_files, {"values-eks.yaml", "values-aks.yaml", "values-gke.yaml"})

    def test_every_element_deploys_the_same_chart_path(self):
        # The template uses one fixed source.path for every generated
        # Application -- the portability claim at the ArgoCD layer.
        self.assertEqual(self.appset["spec"]["template"]["spec"]["source"]["path"], "helm/portable-service")

    def test_deletion_does_not_delete_the_workload(self):
        self.assertTrue(self.appset["spec"]["syncPolicy"]["preserveResourcesOnDeletion"])


class ProjectTests(unittest.TestCase):
    def setUp(self):
        docs = _load_all(ARGOCD_DIR / "project.yaml")
        self.assertEqual(len(docs), 1)
        self.project = docs[0]

    def test_is_an_appproject(self):
        self.assertEqual(self.project["kind"], "AppProject")


if __name__ == "__main__":
    unittest.main()
