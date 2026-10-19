"""Rendered-chart checks (`helm template`); skipped when helm isn't installed."""

from __future__ import annotations

import shutil
import subprocess
import unittest

from helpers import CHART_DIR

import yaml_lite

HELM = shutil.which("helm")


def render_text(*extra):
    return subprocess.run([HELM, "template", "multiarch-app", str(CHART_DIR), "--namespace", "web", *extra],
                          capture_output=True, text=True, timeout=120, check=True).stdout


def kinds_by_name(docs):
    return {(d["kind"], d["metadata"]["name"]): d for d in docs}


@unittest.skipIf(HELM is None, "helm is not installed")
class StableOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = yaml_lite.load_all(render_text())
        cls.by_name = kinds_by_name(cls.docs)

    def test_expected_objects_no_canary(self):
        self.assertEqual(sorted(d["kind"] for d in self.docs),
                         ["Deployment", "PodDisruptionBudget", "Service", "ServiceAccount"])

    def test_stable_deployment_node_selector_and_affinity(self):
        dep = self.by_name[("Deployment", "multiarch-app-stable")]
        spec = dep["spec"]["template"]["spec"]
        self.assertEqual(spec["nodeSelector"]["kubernetes.io/arch"], "amd64")
        pref = spec["affinity"]["nodeAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"]
        values = pref[0]["preference"]["matchExpressions"][0]["values"]
        self.assertEqual(values, ["amd64"])
        self.assertEqual(dep["metadata"]["labels"]["app.kubernetes.io/pool"], "stable")

    def test_service_selector_has_no_pool_label(self):
        svc = self.by_name[("Service", "multiarch-app")]
        self.assertNotIn("app.kubernetes.io/pool", svc["spec"]["selector"])

    def test_pdb_selector_matches_both_pools(self):
        pdb = self.by_name[("PodDisruptionBudget", "multiarch-app")]
        self.assertNotIn("app.kubernetes.io/pool", pdb["spec"]["selector"]["matchLabels"])
        self.assertEqual(pdb["spec"]["minAvailable"], 1)

    def test_hardening(self):
        dep = self.by_name[("Deployment", "multiarch-app-stable")]
        pod = dep["spec"]["template"]["spec"]
        container = pod["containers"][0]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        sc = container["securityContext"]
        self.assertTrue(sc["readOnlyRootFilesystem"])
        self.assertFalse(sc["allowPrivilegeEscalation"])
        self.assertEqual(sc["capabilities"]["drop"], ["ALL"])
        self.assertFalse(container["image"].endswith(":latest"))
        self.assertIn("cpu", container["resources"]["requests"])
        self.assertIn("memory", container["resources"]["limits"])


@unittest.skipIf(HELM is None, "helm is not installed")
class CanaryEnabledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = yaml_lite.load_all(render_text("--set", "canary.enabled=true"))
        cls.by_name = kinds_by_name(cls.docs)

    def test_canary_deployment_present_on_arm64(self):
        self.assertIn(("Deployment", "multiarch-app-canary"), self.by_name)
        dep = self.by_name[("Deployment", "multiarch-app-canary")]
        spec = dep["spec"]["template"]["spec"]
        self.assertEqual(spec["nodeSelector"]["kubernetes.io/arch"], "arm64")
        self.assertEqual(dep["spec"]["replicas"], 1)
        self.assertEqual(dep["metadata"]["labels"]["app.kubernetes.io/pool"], "canary")

    def test_service_still_selects_both_pools(self):
        svc = self.by_name[("Service", "multiarch-app")]
        stable = self.by_name[("Deployment", "multiarch-app-stable")]["spec"]["template"]["metadata"]["labels"]
        canary = self.by_name[("Deployment", "multiarch-app-canary")]["spec"]["template"]["metadata"]["labels"]
        for k, v in svc["spec"]["selector"].items():
            self.assertEqual(stable[k], v)
            self.assertEqual(canary[k], v)

    def test_canary_disabled_by_default_removed_cleanly(self):
        docs = yaml_lite.load_all(render_text("--set", "canary.enabled=false"))
        self.assertNotIn("Deployment", {d["kind"] for d in docs if d["metadata"]["name"].endswith("canary")})


@unittest.skipIf(HELM is None, "helm is not installed")
class RollbackIsOneFlagTests(unittest.TestCase):
    """The whole point: moving architecture is a --set flag, not a new image."""

    def test_architecture_flip_changes_only_scheduling(self):
        amd = yaml_lite.load_all(render_text())
        arm = yaml_lite.load_all(render_text("--set", "architecture=arm64"))
        amd_dep = kinds_by_name(amd)[("Deployment", "multiarch-app-stable")]
        arm_dep = kinds_by_name(arm)[("Deployment", "multiarch-app-stable")]
        self.assertEqual(amd_dep["spec"]["template"]["spec"]["nodeSelector"]["kubernetes.io/arch"], "amd64")
        self.assertEqual(arm_dep["spec"]["template"]["spec"]["nodeSelector"]["kubernetes.io/arch"], "arm64")
        amd_image = amd_dep["spec"]["template"]["spec"]["containers"][0]["image"]
        arm_image = arm_dep["spec"]["template"]["spec"]["containers"][0]["image"]
        self.assertEqual(amd_image, arm_image, "the image tag must not change when only scheduling changes")

    def test_required_affinity_when_preferred_is_false(self):
        docs = yaml_lite.load_all(render_text("--set", "affinity.preferred=false"))
        dep = kinds_by_name(docs)[("Deployment", "multiarch-app-stable")]
        affinity = dep["spec"]["template"]["spec"]["affinity"]["nodeAffinity"]
        self.assertIn("requiredDuringSchedulingIgnoredDuringExecution", affinity)
        self.assertNotIn("preferredDuringSchedulingIgnoredDuringExecution", affinity)


@unittest.skipIf(HELM is None, "helm is not installed")
class SchemaRejectsBadValuesTests(unittest.TestCase):
    def test_schema_rejects_latest_and_bad_architecture(self):
        for args in (["--set", "image.tag=latest"], ["--set", "architecture=mips"],
                     ["--set", "replicaCount=0"]):
            with self.subTest(args=args):
                proc = subprocess.run([HELM, "template", "x", str(CHART_DIR), *args],
                                      capture_output=True, text=True, timeout=120, check=False)
                self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
