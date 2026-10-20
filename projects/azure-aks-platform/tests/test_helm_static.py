"""Static assertions on the keyvault-csi-demo chart source (no `helm` binary needed)."""

from __future__ import annotations

import unittest

from helpers import CHART_DIR


def read(*parts):
    return (CHART_DIR / "templates" / "/".join(parts)).read_text()


class HelmStaticTests(unittest.TestCase):
    def test_no_hardcoded_secret_values_in_chart_source(self):
        for path in (CHART_DIR / "templates").rglob("*"):
            if path.is_file():
                text = path.read_text()
                with self.subTest(path=path.name):
                    self.assertNotIn("BEGIN PRIVATE KEY", text)
        values = (CHART_DIR / "values.yaml").read_text()
        self.assertNotIn("BEGIN PRIVATE KEY", values)

    def test_service_account_carries_workload_identity_client_id_annotation(self):
        sa = read("serviceaccount.yaml")
        self.assertIn("azure.workload.identity/client-id:", sa)

    def test_deployment_opts_into_workload_identity_webhook(self):
        deployment = read("deployment.yaml")
        self.assertIn('azure.workload.identity/use: "true"', deployment)

    def test_secret_provider_class_uses_workload_identity_not_pod_identity(self):
        helpers = (CHART_DIR / "templates" / "_helpers.tpl").read_text()
        spc = helpers[helpers.index("spcSpec") :]
        self.assertIn('usePodIdentity: "false"', spc)
        self.assertIn("clientID: {{ .Values.serviceAccount.azureClientId", spc)

    def test_deployment_mounts_the_csi_secrets_store_volume_readonly(self):
        deployment = read("deployment.yaml")
        self.assertIn("driver: secrets-store.csi.k8s.io", deployment)
        self.assertIn("readOnly: true", deployment)

    def test_containers_run_as_non_root_with_dropped_capabilities(self):
        helpers = (CHART_DIR / "templates" / "_helpers.tpl").read_text()
        container_ctx = helpers[helpers.index("containerSecurityContext") :]
        self.assertIn("runAsNonRoot: true", container_ctx)
        self.assertIn("allowPrivilegeEscalation: false", container_ctx)
        self.assertIn("drop:", container_ctx)
        self.assertIn("- ALL", container_ctx)

    def test_pod_disruption_budget_present(self):
        pdb = read("pdb.yaml")
        self.assertIn("kind: PodDisruptionBudget", pdb)

    def test_no_env_var_carries_a_secret_value(self):
        deployment = read("deployment.yaml")
        # Only configuration (paths, required file names, port) as env vars.
        self.assertNotIn("SECRET_VALUE", deployment)
        self.assertIn("SECRETS_DIR", deployment)


if __name__ == "__main__":
    unittest.main()
