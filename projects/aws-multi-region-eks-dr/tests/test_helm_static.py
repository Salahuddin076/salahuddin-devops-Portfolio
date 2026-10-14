"""Static checks on `helm template` output for both value sets (skipped without helm)."""

import shutil
import subprocess
import unittest

from helpers import CHART_DIR

import yaml_lite

HELM = shutil.which("helm")


def render(values_file, *extra):
    out = subprocess.run(
        [HELM, "template", "dr-app", str(CHART_DIR), "--namespace", "orders",
         "-f", str(CHART_DIR / values_file), *extra],
        capture_output=True, text=True, timeout=120, check=True,
    ).stdout
    return yaml_lite.load_all(out)


def by_kind(docs, kind):
    return [d for d in docs if d["kind"] == kind]


@unittest.skipIf(HELM is None, "helm is not installed")
class RenderedChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = {v: render(v) for v in ("values-primary.yaml", "values-dr.yaml")}

    def each(self):
        for values, docs in self.docs.items():
            with self.subTest(values=values):
                yield values, docs

    def test_expected_objects(self):
        for _, docs in self.each():
            kinds = sorted(d["kind"] for d in docs)
            self.assertEqual(kinds, sorted([
                "ConfigMap", "Deployment", "Deployment", "HorizontalPodAutoscaler", "Ingress",
                "NetworkPolicy", "NetworkPolicy", "NetworkPolicy", "PodDisruptionBudget",
                "Service", "ServiceAccount"]))

    def test_every_container_has_resources_probes_and_security_context(self):
        for _, docs in self.each():
            for dep in by_kind(docs, "Deployment"):
                pod = dep["spec"]["template"]["spec"]
                self.assertTrue(pod["securityContext"]["runAsNonRoot"])
                self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
                self.assertFalse(pod["automountServiceAccountToken"])
                for c in pod["containers"]:
                    name = f"{dep['metadata']['name']}/{c['name']}"
                    self.assertIn("cpu", c["resources"]["requests"], name)
                    self.assertIn("memory", c["resources"]["limits"], name)
                    for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
                        self.assertIn(probe, c, name)
                    sc = c["securityContext"]
                    self.assertTrue(sc["runAsNonRoot"], name)
                    self.assertTrue(sc["readOnlyRootFilesystem"], name)
                    self.assertFalse(sc["allowPrivilegeEscalation"], name)
                    self.assertEqual(sc["capabilities"]["drop"], ["ALL"], name)
                    self.assertEqual(sc["seccompProfile"]["type"], "RuntimeDefault", name)
                    self.assertFalse(c["image"].endswith(":latest"), name)

    def test_api_graceful_shutdown_and_zone_spread(self):
        for _, docs in self.each():
            api = next(d for d in by_kind(docs, "Deployment") if d["metadata"]["name"] == "dr-app-api")
            pod = api["spec"]["template"]["spec"]
            sleep = pod["containers"][0]["lifecycle"]["preStop"]["sleep"]["seconds"]
            self.assertGreater(pod["terminationGracePeriodSeconds"], sleep)
            self.assertEqual(pod["containers"][0]["readinessProbe"]["httpGet"]["path"], "/healthz/ready")
            keys = [t["topologyKey"] for t in pod["topologySpreadConstraints"]]
            self.assertIn("topology.kubernetes.io/zone", keys)
            self.assertNotIn("replicas", api["spec"])  # the HPA owns it

    def test_pdb_and_networkpolicy_exist(self):
        for _, docs in self.each():
            pdb = by_kind(docs, "PodDisruptionBudget")[0]
            self.assertGreaterEqual(pdb["spec"]["minAvailable"], 1)
            policies = {p["metadata"]["name"]: p["spec"] for p in by_kind(docs, "NetworkPolicy")}
            deny = policies["dr-app-default-deny"]
            self.assertEqual(deny["policyTypes"], ["Ingress", "Egress"])
            self.assertNotIn("ingress", deny)
            alb = policies["dr-app-api-from-alb"]["ingress"][0]
            self.assertEqual(alb["ports"], [{"protocol": "TCP", "port": 8080}])
            egress_ports = {p["port"] for rule in policies["dr-app-egress"]["egress"] for p in rule["ports"]}
            self.assertTrue({53, 5432, 6379, 443}.issubset(egress_ports))

    def test_ingress_is_for_the_alb_controller(self):
        for values, docs in self.each():
            ing = by_kind(docs, "Ingress")[0]
            self.assertEqual(ing["spec"]["ingressClassName"], "alb")
            ann = ing["metadata"]["annotations"]
            self.assertEqual(ann["alb.ingress.kubernetes.io/target-type"], "ip")
            self.assertEqual(ann["alb.ingress.kubernetes.io/healthcheck-path"], "/healthz/ready")
            hosts = [r["host"] for r in ing["spec"]["rules"]]
            region = "us-east-1" if "primary" in values else "us-west-2"
            self.assertEqual(hosts, ["orders.example.com", f"{region}.orders.example.com"])

    def test_dr_runs_small_with_workers_off(self):
        def worker_replicas(docs):
            return next(d for d in by_kind(docs, "Deployment")
                        if d["metadata"]["name"] == "dr-app-worker")["spec"]["replicas"]

        primary, dr = self.docs["values-primary.yaml"], self.docs["values-dr.yaml"]
        self.assertEqual(worker_replicas(primary), 2)
        self.assertEqual(worker_replicas(dr), 0)
        hpa = {k: by_kind(v, "HorizontalPodAutoscaler")[0]["spec"]["minReplicas"] for k, v in self.docs.items()}
        self.assertLess(hpa["values-dr.yaml"], hpa["values-primary.yaml"])
        cfg = by_kind(dr, "ConfigMap")[0]["data"]
        self.assertIn("us-west-2", cfg["DB_HOST"])
        self.assertEqual(cfg["AWS_REGION"], "us-west-2")

    def test_promotion_values_enable_dr_workers(self):
        # What the failover CLI's helm upgrade sets in the promoted region.
        docs = render("values-dr.yaml", "--set", "workers.enabled=true,workers.replicas=2",
                      "--set", "api.autoscaling.minReplicas=3")
        worker = next(d for d in by_kind(docs, "Deployment") if d["metadata"]["name"] == "dr-app-worker")
        self.assertEqual(worker["spec"]["replicas"], 2)
        self.assertEqual(by_kind(docs, "HorizontalPodAutoscaler")[0]["spec"]["minReplicas"], 3)

    def test_schema_rejects_latest_tag(self):
        proc = subprocess.run(
            [HELM, "template", "dr-app", str(CHART_DIR), "-f", str(CHART_DIR / "values-dr.yaml"),
             "--set", "image.tag=latest"], capture_output=True, text=True, timeout=120, check=False)
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
