"""Static assertions over helm/portable-service: the three cloud overlays
must differ ONLY in the fields that are genuinely cloud-specific (ingress
class/annotations, the ServiceAccount's workload-identity annotation, and
the storage class). That's the whole claim this project makes about
portability, so it's tested directly rather than left to prose.
"""

from __future__ import annotations

import unittest

from helpers import CHART_DIR

import yaml_lite

CLOUDS = ("eks", "aks", "gke")

# Top-level value keys that are allowed to differ between overlays. Anything
# else (image, replicaCount, resources, probes, podDisruptionBudget, ...)
# must be identical, proving the overlays are IAM/ingress/storage diffs, not
# application diffs.
CLOUD_SPECIFIC_KEYS = {"ingress", "serviceAccount", "storage"}


def _load(name: str) -> dict:
    return yaml_lite.load((CHART_DIR / name).read_text())


class BaseValuesTests(unittest.TestCase):
    def setUp(self):
        self.base = _load("values.yaml")

    def test_base_service_account_annotations_are_empty(self):
        self.assertEqual(self.base["serviceAccount"]["annotations"], {})

    def test_base_ingress_and_storage_class_are_blank(self):
        self.assertEqual(self.base["ingress"]["className"], "")
        self.assertEqual(self.base["storage"]["className"], "")

    def test_service_account_name_is_portable_service(self):
        self.assertEqual(self.base["serviceAccount"]["name"], "portable-service")


class OverlayPortabilityTests(unittest.TestCase):
    """The core portability claim: overlays only touch cloud-specific keys."""

    def setUp(self):
        self.base = _load("values.yaml")
        self.overlays = {cloud: _load(f"values-{cloud}.yaml") for cloud in CLOUDS}

    def test_each_overlay_only_sets_cloud_specific_top_level_keys(self):
        for cloud, overlay in self.overlays.items():
            extra = set(overlay.keys()) - CLOUD_SPECIFIC_KEYS
            self.assertEqual(extra, set(), f"{cloud} overlay touches non-cloud-specific keys: {extra}")

    def test_no_overlay_touches_image_replicas_resources_or_probes(self):
        untouched_keys = ("image", "replicaCount", "containerPort", "service", "resources", "probes", "podDisruptionBudget")
        for cloud, overlay in self.overlays.items():
            for key in untouched_keys:
                self.assertNotIn(key, overlay, f"{cloud} overlay should not set {key!r}")

    def test_each_overlay_sets_a_distinct_ingress_class(self):
        classes = {cloud: overlay["ingress"]["className"] for cloud, overlay in self.overlays.items()}
        self.assertEqual(classes, {"eks": "alb", "aks": "azure-application-gateway", "gke": "gce"})

    def test_each_overlay_sets_a_distinct_storage_class(self):
        classes = {cloud: overlay["storage"]["className"] for cloud, overlay in self.overlays.items()}
        self.assertEqual(classes, {"eks": "gp3", "aks": "managed-csi", "gke": "standard-rwo"})

    def test_eks_overlay_uses_irsa_annotation(self):
        ann = self.overlays["eks"]["serviceAccount"]["annotations"]
        self.assertIn("eks.amazonaws.com/role-arn", ann)
        self.assertTrue(ann["eks.amazonaws.com/role-arn"].startswith("arn:aws:iam::"))

    def test_aks_overlay_uses_entra_workload_id_annotation(self):
        ann = self.overlays["aks"]["serviceAccount"]["annotations"]
        self.assertIn("azure.workload.identity/client-id", ann)

    def test_gke_overlay_uses_gke_workload_identity_annotation(self):
        ann = self.overlays["gke"]["serviceAccount"]["annotations"]
        self.assertIn("iam.gke.io/gcp-service-account", ann)
        self.assertTrue(ann["iam.gke.io/gcp-service-account"].endswith(".iam.gserviceaccount.com"))

    def test_no_overlay_sets_a_static_cloud_credential(self):
        forbidden_substrings = ("access_key", "secret_key", "client_secret", "private_key", "password")
        for cloud, overlay in self.overlays.items():
            ann = overlay.get("serviceAccount", {}).get("annotations", {})
            blob = " ".join(f"{k}={v}" for k, v in ann.items()).lower()
            for bad in forbidden_substrings:
                self.assertNotIn(bad, blob, f"{cloud} overlay annotation looks like a static credential: {bad}")

    def test_no_overlay_has_a_matching_service_account_name_override(self):
        # The same ServiceAccount name everywhere is what lets the identity
        # bindings module bind all three clouds to one subject.
        for cloud, overlay in self.overlays.items():
            self.assertNotIn("name", overlay.get("serviceAccount", {}), f"{cloud} overlay should not rename the ServiceAccount")


class ChartMetadataTests(unittest.TestCase):
    def test_chart_yaml_exists_and_has_a_name(self):
        chart = yaml_lite.load((CHART_DIR / "Chart.yaml").read_text())
        self.assertEqual(chart.get("name"), "portable-service")


if __name__ == "__main__":
    unittest.main()
