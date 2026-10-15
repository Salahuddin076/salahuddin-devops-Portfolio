"""Rendered chart per environment, plus kubeconform on the renders and the Argo CD manifests.

Skipped when helm (or kubeconform) isn't installed. kubeconform fetches CRD
schemas from the community catalog; if a fetch fails the test skips with the
reason instead of passing silently.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import CHART_DIR, CONFIG_REPO, CRD_SCHEMA_LOCATION, ENVS, SAMPLES, SCRIPTS_DIR

import yaml_lite

HELM = shutil.which("helm")
KUBECONFORM = shutil.which("kubeconform")
K8S_VERSION = "1.34.0"


def render(env, *extra, check=True):
    proc = subprocess.run([HELM, "template", "orders-api", str(CHART_DIR), "--namespace", f"orders-{env}",
                           "-f", str(CONFIG_REPO / "envs" / env / "values.yaml"), *extra],
                          capture_output=True, text=True, timeout=120, check=False)
    if check and proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return proc


def objects(env):
    docs = yaml_lite.load_all(render(env).stdout)
    return {(d["kind"], d["metadata"]["name"]): d for d in docs}


@unittest.skipIf(HELM is None, "helm is not installed")
class RenderedChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.objs = {env: objects(env) for env in ENVS}

    def workload(self, env):
        kind = "Rollout" if env == "prod" else "Deployment"
        return self.objs[env][(kind, "orders-api")]

    def test_lint_each_env(self):
        for env in ENVS:
            with self.subTest(env=env):
                proc = subprocess.run([HELM, "lint", str(CHART_DIR), "-f", str(CONFIG_REPO / "envs" / env / "values.yaml")],
                                      capture_output=True, text=True, timeout=120)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_objects_per_env(self):
        common = ["ExternalSecret", "HorizontalPodAutoscaler", "Ingress", "NetworkPolicy", "PodDisruptionBudget",
                  "Service", "ServiceAccount", "ServiceMonitor"]
        self.assertEqual(sorted(k for k, _ in self.objs["dev"]), sorted(common + ["Deployment"]))
        self.assertEqual(sorted(k for k, _ in self.objs["staging"]), sorted(common + ["Deployment"]))
        self.assertEqual(sorted(k for k, _ in self.objs["prod"]), sorted(common + ["AnalysisTemplate", "Rollout"]))
        for env in ENVS:
            self.assertNotIn("Secret", {k for k, _ in self.objs[env]}, "secrets come from External Secrets only")

    def test_pod_hardening(self):
        for env in ENVS:
            with self.subTest(env=env):
                pod = self.workload(env)["spec"]["template"]["spec"]
                self.assertIs(pod["automountServiceAccountToken"], False)
                self.assertEqual(pod["securityContext"]["runAsNonRoot"], True)
                self.assertEqual(pod["securityContext"]["runAsUser"], 10001)
                self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
                (c,) = pod["containers"]
                sc = c["securityContext"]
                self.assertEqual((sc["allowPrivilegeEscalation"], sc["readOnlyRootFilesystem"], sc["privileged"]),
                                 (False, True, False))
                self.assertEqual(sc["capabilities"]["drop"], ["ALL"])
                self.assertTrue({"cpu", "memory"} <= set(c["resources"]["requests"]))
                self.assertIn("memory", c["resources"]["limits"])
                self.assertEqual(c["livenessProbe"]["httpGet"]["path"], "/healthz")
                self.assertEqual(c["readinessProbe"]["httpGet"]["path"], "/readyz")
                self.assertEqual(c["envFrom"], [{"secretRef": {"name": "orders-api-secrets"}}])
                sa = self.objs[env][("ServiceAccount", "orders-api")]
                self.assertIs(sa["automountServiceAccountToken"], False)

    def test_image_tag_comes_from_the_env_file(self):
        import promote
        for env in ENVS:
            with self.subTest(env=env):
                tag = promote.read_tag((CONFIG_REPO / "envs" / env / "values.yaml").read_text())
                image = self.workload(env)["spec"]["template"]["spec"]["containers"][0]["image"]
                self.assertEqual(image, f"ghcr.io/example-org/orders-api:{tag}")

    def test_hpa_owns_replicas_and_targets_the_right_kind(self):
        for env in ENVS:
            with self.subTest(env=env):
                self.assertNotIn("replicas", self.workload(env)["spec"])
                ref = self.objs[env][("HorizontalPodAutoscaler", "orders-api")]["spec"]["scaleTargetRef"]
                self.assertEqual(ref["kind"], "Rollout" if env == "prod" else "Deployment")
                self.assertEqual(ref["apiVersion"], "argoproj.io/v1alpha1" if env == "prod" else "apps/v1")

    def test_prod_canary_steps_and_analysis(self):
        rollout = self.workload("prod")
        steps = rollout["spec"]["strategy"]["canary"]["steps"]
        self.assertEqual([s["setWeight"] for s in steps if "setWeight" in s], [10, 50, 100])
        self.assertEqual(list(steps[0]), ["setWeight"])
        first_analysis = next(i for i, s in enumerate(steps) if "analysis" in s)
        self.assertLess(first_analysis, next(i for i, s in enumerate(steps) if s.get("setWeight") == 50))
        template = self.objs["prod"][("AnalysisTemplate", "orders-api-success-rate")]
        for s in (s for s in steps if "analysis" in s):
            self.assertEqual(s["analysis"]["templates"], [{"templateName": template["metadata"]["name"]}])
            self.assertEqual(s["analysis"]["args"][0]["valueFrom"], {"podTemplateHashValue": "Latest"})
        metric = template["spec"]["metrics"][0]
        query = metric["provider"]["prometheus"]["query"]
        self.assertIn('code!~"5.."', query)
        self.assertIn('rollouts_pod_template_hash="{{args.canary-hash}}"', query)
        self.assertIn('namespace="orders-prod"', query)
        self.assertEqual(metric["successCondition"], "len(result) > 0 && result[0] >= 0.99")

    def test_network_policy_default_deny_shape(self):
        np = self.objs["dev"][("NetworkPolicy", "orders-api")]["spec"]
        self.assertEqual(np["policyTypes"], ["Ingress", "Egress"])
        allowed = [p["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] for p in np["ingress"][0]["from"]]
        self.assertEqual(allowed, ["ingress-nginx", "monitoring"])
        self.assertEqual([e["ports"][0]["port"] for e in np["egress"]], [53, 5432])

    def test_external_secret_store_per_env(self):
        for env in ENVS:
            with self.subTest(env=env):
                es = self.objs[env][("ExternalSecret", "orders-api")]["spec"]
                self.assertEqual(es["secretStoreRef"], {"kind": "ClusterSecretStore", "name": f"aws-secrets-manager-{env}"})
                self.assertEqual(es["data"][0]["remoteRef"]["key"], f"example/orders-api/{env}/database")

    def test_mutable_or_missing_tags_do_not_render(self):
        for tag in ("latest", "main", "v1.3.0"):
            with self.subTest(tag=tag):
                proc = render("dev", "--set", f"image.tag={tag}", check=False)
                self.assertNotEqual(proc.returncode, 0)
        proc = subprocess.run([HELM, "template", "x", str(CHART_DIR)], capture_output=True, text=True, timeout=120)
        self.assertNotEqual(proc.returncode, 0, "the chart has no default tag")
        self.assertIn("image.tag is required", proc.stderr)

    def test_drift_sample_matches_the_current_render(self):
        self.assertEqual((SAMPLES / "desired" / "dev.yaml").read_text(), render("dev").stdout,
                         "re-render sample-data/desired/dev.yaml (see README)")


_CACHE: list[str] = []


def setUpModule():
    _CACHE.append(tempfile.mkdtemp(prefix="kc-cache-"))


def tearDownModule():
    shutil.rmtree(_CACHE.pop(), ignore_errors=True)


def kubeconform(*args, stdin=None, extra_locations=()):
    cmd = [KUBECONFORM, "-strict", "-summary", "-kubernetes-version", K8S_VERSION, "-cache", _CACHE[0],
           "-schema-location", "default", *[x for loc in extra_locations for x in ("-schema-location", loc)],
           "-schema-location", CRD_SCHEMA_LOCATION, *args]
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=300)


@unittest.skipIf(HELM is None or KUBECONFORM is None, "helm or kubeconform is not installed")
class KubeconformTests(unittest.TestCase):
    def assertValid(self, proc, expected):
        out = proc.stdout + proc.stderr
        if "could not find schema" in out or "failed downloading" in out or "no such host" in out:
            self.skipTest(f"CRD schema fetch failed: {out.strip().splitlines()[0]}")
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn(expected, out)

    def test_each_env_render(self):
        counts = {"dev": 9, "staging": 9, "prod": 10}
        for env in ENVS:
            with self.subTest(env=env):
                proc = kubeconform(stdin=render(env).stdout)
                n = counts[env]
                self.assertValid(proc, f"{n} resources found parsing stdin - Valid: {n}, Invalid: 0, Errors: 0, Skipped: 0")

    def test_argocd_manifests(self):
        proc = kubeconform(str(CONFIG_REPO / "argocd"))
        self.assertValid(proc, "Summary: 5 resources found in 5 files - Valid: 5, Invalid: 0, Errors: 0, Skipped: 0")

    def test_schemas_are_really_applied(self):
        appset = (CONFIG_REPO / "argocd" / "applicationsets" / "orders-api.yaml").read_text()
        bad = appset.replace("  goTemplate: true\n", "  goTemplate: true\n  notAField: 1\n")
        proc = kubeconform(stdin=bad)
        out = proc.stdout + proc.stderr
        if "could not find schema" in out:
            self.skipTest("CRD schema fetch failed")
        self.assertIn("Invalid: 1", out)

    def test_platform_manifests_with_repaired_store_schema(self):
        with tempfile.TemporaryDirectory(prefix="patched-") as out:
            proc = subprocess.run([sys.executable, str(SCRIPTS_DIR / "patch_catalog_schema.py"), "--out", out,
                                   "external-secrets.io/clustersecretstore_v1"], capture_output=True, text=True,
                                  timeout=120)
            if proc.returncode != 0:
                self.skipTest(f"catalog fetch failed: {proc.stderr.strip()}")
            loc = str(Path(out) / "{{.Group}}" / "{{.ResourceKind}}_{{.ResourceAPIVersion}}.json")
            res = kubeconform(str(CONFIG_REPO / "platform"), extra_locations=[loc])
            self.assertValid(res, "6 resources found in 2 files - Valid: 6, Invalid: 0, Errors: 0, Skipped: 0")


if __name__ == "__main__":
    unittest.main()
