"""drift_report.py: field-level drift, the ignore rules, and the shipped samples."""

from __future__ import annotations

import copy
import json
import unittest

from helpers import CONFIG_REPO, FIXTURES, SAMPLES

import drift_report as dr

DESIRED = dr.load_docs(str(FIXTURES / "drift" / "desired.yaml"))
LIVE = dr.load_docs(str(FIXTURES / "drift" / "live.yaml"))


def by_res(rep):
    return {r["resource"]: r for r in rep["resources"]}


def deployment(docs):
    return next(d for d in docs if d["kind"] == "Deployment")


class DriftTests(unittest.TestCase):
    def test_no_drift_despite_defaults_status_and_metadata(self):
        rep = dr.report(DESIRED, LIVE)
        self.assertEqual(rep["summary"]["drifted"], 0, dr.render_text(rep))
        self.assertEqual({r["state"] for r in rep["resources"]}, {"in-sync"})

    def test_image_drift(self):
        live = copy.deepcopy(LIVE)
        deployment(live)["spec"]["template"]["spec"]["containers"][0]["image"] = "ghcr.io/example-org/web:hotfix"
        rep = dr.report(DESIRED, live)
        dep = by_res(rep)["Deployment/web"]
        self.assertEqual(dep["state"], "drift")
        self.assertEqual(dep["fields"], [{
            "op": "~", "path": "spec.template.spec.containers[web].image",
            "desired": "ghcr.io/example-org/web:1111111111111111111111111111111111111111",
            "live": "ghcr.io/example-org/web:hotfix"}])
        self.assertEqual(rep["summary"]["drifted"], 1)

    def test_hpa_replicas_are_ignored(self):
        rep = dr.report(DESIRED, LIVE)
        dep = by_res(rep)["Deployment/web"]
        self.assertEqual(dep["state"], "in-sync")
        self.assertIn("spec.replicas", dep["ignored"])
        self.assertEqual(rep["summary"]["hpa_managed"], ["Deployment/web"])

    def test_replicas_count_as_drift_without_an_hpa(self):
        desired = [d for d in DESIRED if d["kind"] != "HorizontalPodAutoscaler"]
        live = [d for d in LIVE if d["kind"] != "HorizontalPodAutoscaler"]
        dep = by_res(dr.report(desired, live))["Deployment/web"]
        self.assertEqual(dep["fields"], [{"op": "~", "path": "spec.replicas", "desired": 2, "live": 5}])

    def test_app_ignore_differences_apply_without_an_hpa(self):
        desired = [d for d in DESIRED if d["kind"] != "HorizontalPodAutoscaler"]
        live = [d for d in LIVE if d["kind"] != "HorizontalPodAutoscaler"]
        ignores = dr.app_ignores(str(CONFIG_REPO / "argocd" / "applicationsets" / "orders-api.yaml"))
        self.assertIn(("apps", "Deployment", "/spec/replicas"), ignores)
        self.assertIn(("argoproj.io", "Rollout", "/spec/replicas"), ignores)
        self.assertEqual(by_res(dr.report(desired, live, ignores))["Deployment/web"]["state"], "in-sync")

    def test_added_label_and_annotation(self):
        live = copy.deepcopy(LIVE)
        deployment(live)["metadata"]["labels"]["debug"] = "true"
        deployment(live)["metadata"]["annotations"]["example.com/owner"] = "someone"
        fields = by_res(dr.report(DESIRED, live))["Deployment/web"]["fields"]
        self.assertEqual([(f["op"], f["path"], f["live"]) for f in fields], [
            ("+", "metadata.labels.debug", "true"),
            ("+", 'metadata.annotations["example.com/owner"]', "someone"),
        ])

    def test_injected_container_and_removed_field(self):
        live = copy.deepcopy(LIVE)
        spec = deployment(live)["spec"]["template"]["spec"]
        spec["containers"].append({"name": "debug-shell", "image": "busybox"})
        del spec["containers"][0]["ports"]
        ops = {(f["op"], f["path"]) for f in by_res(dr.report(DESIRED, live))["Deployment/web"]["fields"]}
        self.assertEqual(ops, {("+", "spec.template.spec.containers[debug-shell]"),
                               ("-", "spec.template.spec.containers[web].ports")})

    def test_configmap_value_change_and_number_strings(self):
        live = copy.deepcopy(LIVE)
        cm = next(d for d in live if d["kind"] == "ConfigMap")
        cm["data"]["LOG_LEVEL"] = "debug"
        cm["data"]["WORKERS"] = 4  # same value, different YAML type: not drift
        fields = by_res(dr.report(DESIRED, live))["ConfigMap/web-config"]["fields"]
        self.assertEqual(fields, [{"op": "~", "path": "data.LOG_LEVEL", "desired": "info", "live": "debug"}])

    def test_missing_and_extra_resources(self):
        live = [d for d in LIVE if d["kind"] != "ConfigMap"]
        live.append({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "hand-made"}})
        states = {r["resource"]: r["state"] for r in dr.report(DESIRED, live)["resources"]}
        self.assertEqual(states["ConfigMap/web-config"], "missing")
        self.assertEqual(states["Secret/hand-made"], "extra")

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            dr.load_docs(str(FIXTURES / "drift" / "does-not-exist.json"))


class SampleTests(unittest.TestCase):
    """The shipped samples: the dev render vs a clean export and one after `kubectl edit`."""

    def setUp(self):
        self.desired = dr.load_docs(str(SAMPLES / "desired" / "dev.yaml"))

    def test_in_sync_sample(self):
        live = dr.load_docs(str(SAMPLES / "live" / "dev-in-sync.json"))
        rep = dr.report(self.desired, live)
        self.assertEqual(rep["summary"]["drifted"], 0, dr.render_text(rep))
        self.assertIn("spec.replicas", by_res(rep)["Deployment/orders-api"]["ignored"])

    def test_drifted_sample_shows_the_manual_edit(self):
        live = dr.load_docs(str(SAMPLES / "live" / "dev-drifted.json"))
        rep = dr.report(self.desired, live)
        self.assertEqual(rep["summary"]["drifted"], 1)
        fields = by_res(rep)["Deployment/orders-api"]["fields"]
        self.assertEqual(sorted((f["op"], f["path"]) for f in fields), [
            ("+", "metadata.labels.debug"),
            ("~", "spec.template.spec.containers[orders-api].image"),
        ])
        live_by_path = {f["path"]: f["live"] for f in fields}
        self.assertEqual(live_by_path["metadata.labels.debug"], "true")
        self.assertEqual(live_by_path["spec.template.spec.containers[orders-api].image"],
                         "ghcr.io/example-org/orders-api:hotfix-manual")

    def test_samples_are_kubectl_style_lists_with_noise(self):
        raw = json.loads((SAMPLES / "live" / "dev-in-sync.json").read_text())
        self.assertEqual(raw["kind"], "List")
        dep = next(i for i in raw["items"] if i["kind"] == "Deployment")
        self.assertIn("managedFields", dep["metadata"])
        self.assertIn("status", dep)
        self.assertNotIn("replicas", deployment(self.desired)["spec"], "the HPA owns replicas")


if __name__ == "__main__":
    unittest.main()
