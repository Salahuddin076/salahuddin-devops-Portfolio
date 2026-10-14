"""Rendered-chart checks (`helm template`); skipped when helm isn't installed."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest

from helpers import CHART_DIR, TERRAFORM_DIR

import scan_manifests
import yaml_lite

HELM = shutil.which("helm")


def render_text(*extra):
    return subprocess.run([HELM, "template", "secure-frontend", str(CHART_DIR), "--namespace", "web", *extra],
                          capture_output=True, text=True, timeout=120, check=True).stdout


def kinds(docs):
    return {d["kind"]: d for d in docs}


@unittest.skipIf(HELM is None, "helm is not installed")
class RenderedChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = render_text()
        cls.docs = yaml_lite.load_all(cls.text)
        cls.by_kind = kinds(cls.docs)
        cls.pod = cls.by_kind["Deployment"]["spec"]["template"]["spec"]
        cls.container = cls.pod["containers"][0]

    def test_expected_objects_and_no_secret_object(self):
        self.assertEqual(sorted(d["kind"] for d in self.docs),
                         ["Deployment", "NetworkPolicy", "PodDisruptionBudget", "SecretProviderClass",
                          "Service", "ServiceAccount"])

    def test_secretproviderclass_uses_aws_pod_identity_and_jmespath(self):
        spc = self.by_kind["SecretProviderClass"]
        self.assertEqual(spc["apiVersion"], "secrets-store.csi.x-k8s.io/v1")
        params = spc["spec"]["parameters"]
        self.assertEqual(spc["spec"]["provider"], "aws")
        self.assertEqual(params["usePodIdentity"], "true")
        self.assertEqual(params["region"], "us-east-1")
        objects = yaml_lite.load_all(params["objects"])[0]
        db, api = objects
        self.assertEqual(db["objectName"], "secure-frontend/db-credentials")
        # jmesPath key -> file name, exactly as values.yaml maps them.
        values = yaml_lite.load_all((CHART_DIR / "values.yaml").read_text())[0]
        self.assertEqual({j["path"]: j["objectAlias"] for j in db["jmesPath"]}, values["secrets"]["db"]["keys"])
        self.assertEqual(sorted(values["secrets"]["db"]["keys"]), ["host", "password", "username"])
        self.assertEqual((api["objectName"], api["objectAlias"]), ("secure-frontend/api-key", "api-key"))
        self.assertNotIn("secretObjects", spc["spec"])

    def test_app_is_told_exactly_the_files_the_spc_produces(self):
        env = {e["name"]: e["value"] for e in self.container["env"]}
        self.assertEqual(env["SECRETS_DIR"], "/mnt/secrets")
        self.assertEqual(env["SECRETS_REQUIRED"].split(","), ["db-username", "db-password", "db-host", "api-key"])
        self.assertTrue(all("valueFrom" not in e for e in self.container["env"]))
        self.assertNotIn("envFrom", self.container)

    def test_csi_volume_is_read_only_at_mnt_secrets(self):
        vol = next(v for v in self.pod["volumes"] if v["name"] == "secrets-store")
        self.assertEqual(vol["csi"]["driver"], "secrets-store.csi.k8s.io")
        self.assertTrue(vol["csi"]["readOnly"])
        self.assertEqual(vol["csi"]["volumeAttributes"]["secretProviderClass"], "secure-frontend")
        mount = next(m for m in self.container["volumeMounts"] if m["name"] == "secrets-store")
        self.assertEqual(mount["mountPath"], "/mnt/secrets")
        self.assertTrue(mount["readOnly"])

    def test_hardening(self):
        self.assertFalse(self.pod["automountServiceAccountToken"])
        self.assertFalse(self.by_kind["ServiceAccount"]["automountServiceAccountToken"])
        self.assertTrue(self.pod["securityContext"]["runAsNonRoot"])
        self.assertEqual(self.pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
        sc = self.container["securityContext"]
        self.assertTrue(sc["readOnlyRootFilesystem"])
        self.assertFalse(sc["allowPrivilegeEscalation"])
        self.assertEqual(sc["capabilities"]["drop"], ["ALL"])
        self.assertEqual(sc["seccompProfile"]["type"], "RuntimeDefault")
        for probe, path in (("startupProbe", "/healthz"), ("readinessProbe", "/healthz"), ("livenessProbe", "/livez")):
            self.assertEqual(self.container[probe]["httpGet"]["path"], path)
        self.assertIn("cpu", self.container["resources"]["requests"])
        self.assertIn("memory", self.container["resources"]["limits"])
        self.assertFalse(self.container["image"].endswith(":latest"))

    def test_pdb_and_network_policy(self):
        self.assertEqual(self.by_kind["PodDisruptionBudget"]["spec"]["minAvailable"], 1)
        np = self.by_kind["NetworkPolicy"]["spec"]
        self.assertEqual(np["policyTypes"], ["Ingress", "Egress"])
        ports = [p["port"] for rule in np["egress"] for p in rule["ports"]]
        self.assertEqual(sorted(set(ports)), [53], "the app needs DNS only; ASCP does the AWS calls")
        # No ipBlock at all: not the Pod Identity agent (169.254.170.23), not AWS endpoints.
        self.assertFalse(any(peer.get("ipBlock") for rule in np["egress"] for peer in rule["to"]))

    def test_checksum_tracks_the_mapping_not_the_values(self):
        ann = lambda docs: kinds(docs)["Deployment"]["spec"]["template"]["metadata"]["annotations"]  # noqa: E731
        base = ann(self.docs)["checksum/secretproviderclass"]
        self.assertRegex(base, r"^[0-9a-f]{64}$")
        moved = ann(yaml_lite.load_all(render_text("--set", "secrets.db.keys.host=db-endpoint")))
        self.assertNotEqual(moved["checksum/secretproviderclass"], base)
        poll = ann(yaml_lite.load_all(render_text("--set", "secrets.appPollSeconds=30")))
        self.assertEqual(poll["checksum/secretproviderclass"], base)

    def test_rendered_chart_passes_scan_manifests(self):
        self.assertEqual([f.text() for f in scan_manifests.scan_text(self.text, "chart")], [])

    def test_sync_enabled_adds_secret_objects_and_scanner_warns(self):
        docs = yaml_lite.load_all(render_text("--set", "secrets.sync.enabled=true"))
        spc = kinds(docs)["SecretProviderClass"]["spec"]
        self.assertEqual(spc["secretObjects"][0]["secretName"], "secure-frontend-synced")
        self.assertEqual([d["key"] for d in spc["secretObjects"][0]["data"]],
                         ["username", "password", "host", "api-key"])
        self.assertEqual([f.rule for f in scan_manifests.scan_docs(docs, "chart")], ["SM007"])

    def test_schema_rejects_latest_and_single_replica(self):
        for args in (["--set", "image.tag=latest"], ["--set", "replicaCount=1"],
                     ["--set", "secrets.mountPath=relative"]):
            with self.subTest(args=args):
                proc = subprocess.run([HELM, "template", "x", str(CHART_DIR), *args],
                                      capture_output=True, text=True, timeout=120, check=False)
                self.assertNotEqual(proc.returncode, 0)


class ChartTerraformAgreementTests(unittest.TestCase):
    """Names that must match across Terraform and the chart (no helm needed)."""

    def tf_default(self, var):
        text = (TERRAFORM_DIR / "modules" / "secrets-store-csi" / "variables.tf").read_text()
        block = text[text.index(f'variable "{var}"'):]
        return re.search(r'default\s*=\s*"([^"]+)"', block).group(1)

    def test_defaults_agree(self):
        values = yaml_lite.load_all((CHART_DIR / "values.yaml").read_text())[0]
        self.assertEqual(values["serviceAccount"]["name"], self.tf_default("service_account"))
        self.assertEqual(values["secrets"]["db"]["secretName"], self.tf_default("db_secret_name"))
        self.assertEqual(values["secrets"]["apiKey"]["secretName"], self.tf_default("api_key_secret_name"))


if __name__ == "__main__":
    unittest.main()
