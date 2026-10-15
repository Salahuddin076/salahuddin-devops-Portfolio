"""Generator output shape, references between rules, determinism, and generated/ being current."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import GENERATED, SLO_DIR

import slogen
import yaml_lite

METRIC = re.compile(r"\bslo:[a-z_]+:[a-z_0-9]+")


def all_rules(services):
    out = []
    for svc in services:
        for g in slogen.service_rules(svc)["groups"]:
            out += [(svc, g["name"], r) for r in g["rules"]]
    return out


class GeneratorShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.services = slogen.load_all(SLO_DIR)
        cls.rules = all_rules(cls.services)

    def test_three_services_four_slos(self):
        self.assertEqual([s["service"] for s in self.services], ["checkout-api", "orders-worker", "public-website"])
        self.assertEqual(sum(len(s["slos"]) for s in self.services), 4)
        for svc in self.services:
            for slo in svc["slos"]:
                self.assertIn(slo["window"], ("28d", "30d"))

    def test_every_slo_gets_every_window(self):
        for svc in self.services:
            for slo in svc["slos"]:
                labels = {"service": svc["service"], "slo": slo["name"]}
                records = {r["record"] for s, _, r in self.rules if "record" in r and r["labels"] == labels}
                for w in slogen.SLI_WINDOWS:
                    self.assertIn(f"slo:sli_error:ratio_rate{w}", records, (labels, w))
                self.assertIn(f"slo:sli_error:ratio_rate{slo['window']}", records)
                self.assertIn("slo:period_error_budget_remaining:ratio", records)

    def test_sli_expression_shape(self):
        slo = self.services[0]["slos"][0]
        expr = slogen.sli_error_expr(slo, "1h")
        self.assertNotIn("$window", expr)
        self.assertIn("[1h]", expr)
        self.assertIn("or vector(0)", expr)
        self.assertTrue(expr.startswith("1 - ("))

    def test_alert_expressions_reference_existing_recording_rules(self):
        recorded = {(r["record"], r["labels"]["service"], r["labels"]["slo"]) for _, _, r in self.rules if "record" in r}
        alerts = [(s, r) for s, _, r in self.rules if "alert" in r]
        self.assertEqual(len(alerts), 4 + 4 + 4 + 3)
        for svc, alert in alerts:
            names = METRIC.findall(alert["expr"])
            self.assertEqual(len(names), 2, alert["alert"])
            sel = re.search(r'service="([^"]+)",slo="([^"]+)"', alert["expr"])
            for name in names:
                self.assertIn((name, sel.group(1), sel.group(2)), recorded, alert["alert"])
        # Meta recording rules read the 5m and period ratios they need.
        for _, _, r in self.rules:
            if "record" in r:
                for name in METRIC.findall(r["expr"]):
                    self.assertIn((name, r["labels"]["service"], r["labels"]["slo"]), recorded, r["record"])

    def test_alert_windows_and_thresholds_match_the_tier(self):
        for _, _, r in self.rules:
            if "alert" not in r:
                continue
            tier = slogen.TIERS_BY_NAME[r["labels"]["tier"]]
            with self.subTest(alert=r["alert"]):
                self.assertIn(f"slo:sli_error:ratio_rate{tier.long}{{", r["expr"])
                self.assertIn(f"slo:sli_error:ratio_rate{tier.short}{{", r["expr"])
                self.assertEqual(r["expr"].count(f"> ({slogen.dec(tier.factor)} * "), 2)
                self.assertIn("\nand\n", r["expr"])
                self.assertEqual(r["labels"]["severity"], tier.severity)
                self.assertEqual(r["for"], "2m" if tier.severity == "page" else "15m")
                self.assertTrue(r["annotations"]["runbook_url"].endswith(f"-{tier.speed}-burn.md"))
                self.assertIn("runbooks/", r["annotations"]["runbook_url"])
                self.assertIn("$value", r["annotations"]["description"])

    def test_website_has_no_6h_page(self):
        website = [r["alert"] for s, _, r in self.rules if "alert" in r and s["service"] == "public-website"]
        self.assertEqual(website, ["PublicWebsiteAvailabilityBurnPage1h", "PublicWebsiteAvailabilityBurnTicket1d",
                                   "PublicWebsiteAvailabilityBurnTicket3d"])

    def test_no_duplicate_rule_or_group_names(self):
        alerts = [r["alert"] for _, _, r in self.rules if "alert" in r] + ["Watchdog"]
        self.assertEqual(len(alerts), len(set(alerts)))
        groups = [g for _, g, _ in self.rules]
        self.assertEqual(len(set(groups)), 8)
        series = [(r["record"], r["labels"]["service"], r["labels"]["slo"]) for _, _, r in self.rules if "record" in r]
        self.assertEqual(len(series), len(set(series)))

    def test_budget_summary_math_in_annotations(self):
        rule = next(r for _, _, r in self.rules if r.get("alert") == "CheckoutApiAvailabilityBurnPage1h")
        self.assertIn("consumes 2% of the 30d budget every 1h and exhausts it in 2.1d", rule["annotations"]["description"])
        rule = next(r for _, _, r in self.rules if r.get("alert") == "OrdersWorkerFreshnessBurnTicket3d")
        self.assertIn("consumes 10.71% of the 28d budget every 3d", rule["annotations"]["description"])

    def test_watchdog(self):
        rule = slogen.meta_rules()["groups"][0]["rules"][0]
        self.assertEqual((rule["alert"], rule["expr"]), ("Watchdog", "vector(1)"))
        self.assertTrue(rule["annotations"]["runbook_url"].endswith("runbooks/watchdog.md"))


class GeneratedFilesTests(unittest.TestCase):
    def test_rule_files_parse_and_match_the_model(self):
        services = slogen.load_all(SLO_DIR)
        for svc in services:
            path = GENERATED / "prometheus" / f"{svc['service']}.rules.yml"
            self.assertEqual(yaml_lite.load_all(path.read_text())[0], slogen.service_rules(svc))
            crd = yaml_lite.load_all((GENERATED / "kubernetes" / f"{svc['service']}.prometheusrule.yaml").read_text())[0]
            self.assertEqual((crd["apiVersion"], crd["kind"]), ("monitoring.coreos.com/v1", "PrometheusRule"))
            self.assertEqual(crd["metadata"]["namespace"], "observability")
            self.assertEqual(crd["spec"], slogen.service_rules(svc))

    def test_dashboards(self):
        for svc in slogen.load_all(SLO_DIR):
            dash = json.loads((GENERATED / "grafana" / f"{svc['service']}.dashboard.json").read_text())
            with self.subTest(service=svc["service"]):
                for key in ("title", "uid", "schemaVersion", "panels", "templating", "time"):
                    self.assertIn(key, dash)
                self.assertEqual(dash["uid"], f"slo-{svc['service']}")
                ids = [p["id"] for p in dash["panels"]]
                self.assertEqual(len(ids), len(set(ids)))
                types = [p["type"] for p in dash["panels"]]
                self.assertEqual(types, ["row", "stat", "stat", "timeseries"] * len(svc["slos"]))
                titles = [p["title"] for p in dash["panels"] if p["type"] != "row"]
                self.assertIn("Error budget remaining", titles)
                self.assertIn("Burn rate", titles)
                for p in dash["panels"]:
                    self.assertLessEqual(p["gridPos"]["x"] + p["gridPos"]["w"], 24)
                    for t in p.get("targets", []):
                        self.assertIn(f'service="{svc["service"]}"', t["expr"])

    def test_generation_is_deterministic(self):
        services = slogen.load_all(SLO_DIR)
        first = slogen.render_all(services)
        second = slogen.render_all(slogen.load_all(SLO_DIR))
        self.assertEqual(first, second)
        self.assertEqual(list(first), sorted(first))

    def test_regenerating_gives_no_diff(self):
        n, drift = slogen.generate(SLO_DIR, GENERATED, check=True)
        self.assertEqual(drift, [], "run: python3 generator/slogen.py generate")
        self.assertEqual(n, 12)

    def test_check_mode_detects_drift_and_stale_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "generated"
            shutil.copytree(GENERATED, out)
            (out / "prometheus" / "meta.rules.yml").write_text("edited\n")
            (out / "prometheus" / "old.rules.yml").write_text("stale\n")
            (out / "grafana" / "checkout-api.dashboard.json").unlink()
            _, drift = slogen.generate(SLO_DIR, out, check=True)
            self.assertEqual(len(drift), 3, drift)
            self.assertIn("changed: prometheus/meta.rules.yml", drift)
            self.assertIn("missing: grafana/checkout-api.dashboard.json", drift)
            self.assertIn("stale: prometheus/old.rules.yml", drift)
            slogen.generate(SLO_DIR, out, check=False)
            self.assertFalse((out / "prometheus" / "old.rules.yml").exists())
            self.assertEqual(slogen.generate(SLO_DIR, out, check=True)[1], [])


class SLOValidationTests(unittest.TestCase):
    def write(self, tmp, data):
        path = Path(tmp) / "x.json"
        path.write_text(json.dumps(data))
        return path

    def base(self):
        return json.loads((SLO_DIR / "orders-worker.json").read_text())

    def test_valid_file_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(slogen.load_service(self.write(tmp, self.base()))["service"], "orders-worker")

    def test_invalid_files_are_rejected(self):
        cases = {
            "objective": lambda d: d["slos"][0].update(objective=100),
            "window": lambda d: d["slos"][0].update(window="6h"),
            "$window": lambda d: d["slos"][0]["sli"].update(good="sum(rate(x[5m]))"),
            "unknown tier": lambda d: d["slos"][0]["alerting"].update(tiers=["page-2h"]),
            "at least one": lambda d: d["slos"][0]["alerting"].update(tiers=[]),
            "slug": lambda d: d.update(service="Orders Worker"),
            "duplicate": lambda d: d["slos"].append(dict(d["slos"][0])),
            "missing": lambda d: d.pop("team"),
        }
        for needle, mutate in cases.items():
            data = self.base()
            mutate(data)
            with self.subTest(case=needle), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(slogen.SLOError, re.escape(needle)):
                    slogen.load_service(self.write(tmp, data))


class YamlEmitterTests(unittest.TestCase):
    def test_round_trip(self):
        obj = {"a": "x: y", "b": 1, "c": True, "d": ["p", {"q": "line1\nline2"}], "e": {}, "f": [], "g": 'say "hi"'}
        text = "\n".join(slogen.to_yaml(obj)) + "\n"
        self.assertEqual(yaml_lite.load_all(text)[0], obj)

    def test_header(self):
        self.assertTrue(slogen.yaml_doc({"a": "b"}, "slo/x.json").startswith("# Generated by generator/slogen.py"))
        self.assertIn("\n---\n", slogen.yaml_doc({"a": "b"}, "slo/x.json", True))


if __name__ == "__main__":
    unittest.main()
