"""Rendered chart and generated CRDs: helm lint, object checks, kubeconform with the CRD catalog.

Skipped when helm (or kubeconform) isn't installed. kubeconform fetches the
community CRD catalog over the network; if a schema can't be fetched the
test skips with the reason instead of passing silently.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest

from helpers import CHART_DIR, CRD_SCHEMA_LOCATION, GENERATED

import yaml_lite

HELM = shutil.which("helm")
KUBECONFORM = shutil.which("kubeconform")


def render(*extra):
    out = subprocess.run([HELM, "template", "obs", str(CHART_DIR), "--namespace", "observability", *extra],
                         capture_output=True, text=True, timeout=120, check=True).stdout
    return out, yaml_lite.load_all(out)


@unittest.skipIf(HELM is None, "helm is not installed")
class RenderedChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text, cls.docs = render()
        cls.objs = {(d["kind"], d["metadata"]["name"]): d for d in cls.docs}

    def test_lint(self):
        proc = subprocess.run([HELM, "lint", str(CHART_DIR)], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_objects_and_no_secret(self):
        self.assertEqual(sorted(self.objs), sorted([
            ("AlertmanagerConfig", "slo-routing"), ("ConfigMap", "otel-collector"), ("Deployment", "otel-collector"),
            ("PodDisruptionBudget", "otel-collector"), ("Probe", "blackbox-website"), ("Service", "otel-collector"),
            ("ServiceAccount", "otel-collector"), ("ServiceMonitor", "checkout-api"), ("ServiceMonitor", "orders-worker"),
        ]))
        for d in self.docs:
            self.assertEqual(d["metadata"]["labels"].get("prometheus"), "platform", d["kind"])

    def test_service_monitors_produce_the_sli_job_labels(self):
        for name in ("checkout-api", "orders-worker"):
            sm = self.objs[("ServiceMonitor", name)]["spec"]
            self.assertEqual(sm["jobLabel"], "app.kubernetes.io/name")
            self.assertEqual(sm["selector"]["matchLabels"]["app.kubernetes.io/name"], name)
        probe = self.objs[("Probe", "blackbox-website")]["spec"]
        self.assertEqual(probe["jobName"], "blackbox-website")
        self.assertEqual(probe["targets"]["staticConfig"]["static"], ["https://www.example.com"])

    def test_alertmanager_config_routes_inhibition_and_watchdog(self):
        spec = self.objs[("AlertmanagerConfig", "slo-routing")]["spec"]
        routes = spec["route"]["routes"]
        self.assertEqual(routes[0]["receiver"], "deadmans-switch")
        self.assertEqual(routes[0]["matchers"], [{"name": "alertname", "value": "Watchdog", "matchType": "="}])
        self.assertEqual(routes[0]["repeatInterval"], "1m")
        self.assertEqual({r["matchers"][0]["value"]: r["receiver"] for r in routes[1:]},
                         {"page": "pager", "ticket": "ticket"})
        (inhibit,) = spec["inhibitRules"]
        self.assertEqual(inhibit["sourceMatch"][0]["value"], "page")
        self.assertEqual(inhibit["targetMatch"][0]["value"], "ticket")
        self.assertEqual(inhibit["equal"], ["service", "slo"])
        receivers = {r["name"]: r for r in spec["receivers"]}
        self.assertEqual(receivers["pager"]["pagerdutyConfigs"][0]["routingKey"]["name"], "alertmanager-receivers")
        for name in ("ticket", "deadmans-switch"):
            self.assertIn("urlSecret", receivers[name]["webhookConfigs"][0])
            self.assertNotIn("url", receivers[name]["webhookConfigs"][0])

    def test_otel_collector_hardening_and_config(self):
        pod = self.objs[("Deployment", "otel-collector")]["spec"]["template"]["spec"]
        c = pod["containers"][0]
        self.assertEqual(c["image"], "otel/opentelemetry-collector-contrib:0.130.0")
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertTrue(c["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(c["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertIn("limits", c["resources"])
        cfg = yaml_lite.load_all(self.objs[("ConfigMap", "otel-collector")]["data"]["config.yaml"])[0]
        self.assertIn("attributes/scrub-pii", cfg["processors"])
        self.assertRegex(self.objs[("Deployment", "otel-collector")]["spec"]["template"]["metadata"]
                         ["annotations"]["checksum/config"], r"^[0-9a-f]{64}$")

    def test_otel_can_be_disabled(self):
        _, docs = render("--set", "otelCollector.enabled=false", "--set", "probe.enabled=false")
        self.assertEqual(sorted(d["kind"] for d in docs), ["AlertmanagerConfig", "ServiceMonitor", "ServiceMonitor"])

    @unittest.skipIf(KUBECONFORM is None, "kubeconform is not installed")
    def test_kubeconform_chart_and_generated_crds(self):
        with tempfile.TemporaryDirectory() as cache:
            base = [KUBECONFORM, "-strict", "-summary", "-kubernetes-version", "1.34.0", "-cache", cache,
                    "-schema-location", "default", "-schema-location", CRD_SCHEMA_LOCATION]
            for label, args, stdin in (("chart", ["-"], self.text),
                                       ("generated", [str(GENERATED / "kubernetes")], None)):
                proc = subprocess.run(base + args, input=stdin, capture_output=True, text=True, timeout=300)
                out = proc.stdout + proc.stderr
                if re.search(r"could not find schema|failed downloading|no such host|timeout", out, re.I):
                    self.skipTest(f"{label}: schema fetch failed: {out.strip()[-300:]}")
                with self.subTest(label=label):
                    self.assertEqual(proc.returncode, 0, out)
                    self.assertRegex(out, r"Invalid: 0, Errors: 0, Skipped: 0")


if __name__ == "__main__":
    unittest.main()
