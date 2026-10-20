"""Static checks on the Helm chart source (no `helm template` needed -- that
runs separately in CI, since this repo's unit tests must pass without any
external binary)."""

from __future__ import annotations

import unittest

from helpers import CHART_DIR


def read(*parts):
    return (CHART_DIR.joinpath(*parts)).read_text()


class HelmStaticTests(unittest.TestCase):
    def test_chart_yaml_has_required_fields(self):
        chart = read("Chart.yaml")
        self.assertIn("apiVersion: v2", chart)
        self.assertIn("name: pharmacy-service", chart)

    def test_serviceaccount_carries_workload_identity_annotation(self):
        manifest = read("templates", "serviceaccount.yaml")
        self.assertIn("iam.gke.io/gcp-service-account", manifest)
        self.assertIn(".Values.serviceAccount.gcpServiceAccountEmail", manifest)

    def test_deployment_never_mounts_a_key_file_or_env_credential(self):
        manifest = read("templates", "deployment.yaml")
        for forbidden in ("GOOGLE_APPLICATION_CREDENTIALS", "serviceAccountKey", ".json"):
            self.assertNotIn(forbidden, manifest)

    def test_deployment_schedules_via_nodeselector_and_tolerations(self):
        manifest = read("templates", "deployment.yaml")
        self.assertIn("nodeSelector:", manifest)
        self.assertIn(".Values.nodeSelector", manifest)
        self.assertIn(".Values.tolerations", manifest)

    def test_deployment_runs_hardened(self):
        manifest = read("templates", "deployment.yaml")
        self.assertIn("runAsNonRoot: true", manifest)
        self.assertIn("allowPrivilegeEscalation: false", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('drop: ["ALL"]', manifest)

    def test_api_values_target_the_api_pool(self):
        values = read("values.yaml")
        self.assertIn("workload: api", values)
        self.assertIn("workload-pool: api", values)

    def test_ai_values_tolerate_the_ai_pool_taint_and_scale_resources_up(self):
        values = read("values-ai.yaml")
        self.assertIn("workload: ai", values)
        self.assertIn("workload-pool: ai-inference", values)
        self.assertIn("value: ai-inference", values)
        self.assertIn("effect: NoSchedule", values)

    def test_networkpolicy_scopes_ingress_to_named_namespace(self):
        manifest = read("templates", "networkpolicy.yaml")
        self.assertIn(".Values.networkPolicy.ingressNamespace", manifest)
        self.assertIn("NetworkPolicy", manifest)

    def test_pdb_present(self):
        manifest = read("templates", "pdb.yaml")
        self.assertIn("PodDisruptionBudget", manifest)
        self.assertIn("minAvailable", manifest)


if __name__ == "__main__":
    unittest.main()
