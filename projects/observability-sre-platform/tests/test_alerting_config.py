"""Alertmanager routing (local native config and the chart's AlertmanagerConfig template) and the OTel config."""

from __future__ import annotations

import re
import unittest

from helpers import CHART_DIR, LOCAL_ALERTMANAGER, OTEL_CONFIG, SLO_DIR

import slogen
import yaml_lite


def matcher(route):
    return route["matchers"]


class LocalAlertmanagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = yaml_lite.load_all(LOCAL_ALERTMANAGER.read_text())[0]
        cls.routes = cls.cfg["route"]["routes"]

    def test_watchdog_route_is_first_and_frequent(self):
        first = self.routes[0]
        self.assertEqual(first["matchers"], ['alertname="Watchdog"'])
        self.assertEqual(first["receiver"], "deadmans-switch")
        self.assertEqual(first["repeat_interval"], "1m")
        self.assertEqual(first["group_wait"], "0s")
        self.assertNotIn("continue", first)

    def test_page_and_ticket_routes(self):
        by_matcher = {r["matchers"][0]: r["receiver"] for r in self.routes}
        self.assertEqual(by_matcher['severity="page"'], "pager")
        self.assertEqual(by_matcher['severity="ticket"'], "ticket")
        self.assertEqual(self.cfg["route"]["group_by"], ["alertname", "service", "slo"])

    def test_inhibition_ticket_by_page_for_same_slo(self):
        (rule,) = self.cfg["inhibit_rules"]
        self.assertEqual(rule["source_matchers"], ['severity="page"'])
        self.assertEqual(rule["target_matchers"], ['severity="ticket"'])
        self.assertEqual(rule["equal"], ["service", "slo"])

    def test_every_route_has_a_receiver_and_stays_local(self):
        names = {r["name"] for r in self.cfg["receivers"]}
        self.assertEqual(names, {"pager", "ticket", "deadmans-switch"})
        for r in self.routes + [self.cfg["route"]]:
            self.assertIn(r["receiver"], names)
        for r in self.cfg["receivers"]:
            for hook in r["webhook_configs"]:
                self.assertTrue(hook["url"].startswith("http://demo-app:8080/alerts/"))

    def test_generated_severities_are_all_routed(self):
        sev = set()
        for svc in slogen.load_all(SLO_DIR):
            for g in slogen.service_rules(svc)["groups"]:
                sev |= {r["labels"]["severity"] for r in g["rules"] if "alert" in r}
        self.assertEqual(sev, {"page", "ticket"})


class ChartAlertmanagerConfigTests(unittest.TestCase):
    """Static checks on the template text; the rendered object is checked in test_helm_static."""

    def test_no_secret_values_only_references(self):
        text = (CHART_DIR / "templates" / "alertmanagerconfig.yaml").read_text()
        self.assertIn("routingKey:", text)
        self.assertIn("urlSecret:", text)
        self.assertNotRegex(text, r"(?m)^\s*url:\s")
        self.assertNotIn("kind: Secret", text)


class OtelConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = yaml_lite.load_all(OTEL_CONFIG.read_text())[0]

    def test_required_sections(self):
        for section in ("receivers", "processors", "exporters", "service", "extensions"):
            self.assertIn(section, self.cfg)
        self.assertEqual(set(self.cfg["service"]["pipelines"]), {"metrics", "logs", "traces"})

    def test_every_pipeline_references_defined_components(self):
        service = self.cfg["service"]
        for ext in service["extensions"]:
            self.assertIn(ext, self.cfg["extensions"])
        used = {"receivers": set(), "processors": set(), "exporters": set()}
        for name, pipe in service["pipelines"].items():
            for kind in used:
                with self.subTest(pipeline=name, kind=kind):
                    self.assertTrue(pipe[kind], f"{name} has no {kind}")
                    for comp in pipe[kind]:
                        self.assertIn(comp, self.cfg[kind], f"{name} uses undefined {kind[:-1]} {comp}")
                        used[kind].add(comp)
        for kind, names in used.items():
            self.assertEqual(set(self.cfg[kind]), names, f"defined but unused {kind}")

    def test_processor_order(self):
        for name, pipe in self.cfg["service"]["pipelines"].items():
            procs = pipe["processors"]
            self.assertEqual(procs[0], "memory_limiter", name)
            self.assertEqual(procs[-1], "batch", name)
            self.assertIn("attributes/scrub-pii", procs, name)

    def test_pii_scrubbing_actions(self):
        actions = self.cfg["processors"]["attributes/scrub-pii"]["actions"]
        by_key = {a.get("key"): a["action"] for a in actions if "key" in a}
        self.assertEqual(by_key["http.request.header.authorization"], "delete")
        self.assertEqual(by_key["user.email"], "delete")
        self.assertEqual(by_key["enduser.id"], "hash")
        self.assertEqual(by_key["client.address"], "hash")
        self.assertTrue({a["action"] for a in actions} <= {"delete", "hash"})
        pattern = next(a["pattern"] for a in actions if "pattern" in a)
        rx = re.compile(pattern.replace("(?i)", ""), re.I)
        for key in ("db.password", "X-API-Key", "auth_token", "client_secret"):
            self.assertTrue(rx.match(key), key)
        self.assertFalse(rx.match("http.route"))

    def test_exporters_are_placeholders(self):
        exp = self.cfg["exporters"]
        self.assertEqual(set(exp), {"prometheusremotewrite", "otlphttp/loki", "otlp/tempo"})
        for name, conf in exp.items():
            self.assertIn("example.com", conf["endpoint"], name)

    def test_memory_limiter(self):
        ml = self.cfg["processors"]["memory_limiter"]
        self.assertEqual(ml["check_interval"], "1s")
        self.assertLess(ml["spike_limit_percentage"], ml["limit_percentage"])


if __name__ == "__main__":
    unittest.main()
