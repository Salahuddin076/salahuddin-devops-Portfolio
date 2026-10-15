"""The local demo app: deterministic synthetic counters, fault toggles, the webhook sink, over real HTTP."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

import helpers  # noqa: F401  (sys.path)
import demo_app


class SimulatorTests(unittest.TestCase):
    def test_healthy_counts(self):
        sim = demo_app.Simulator()
        for _ in range(10):
            sim.tick()
        self.assertEqual(sim.http, {"200": 200, "500": 0})
        self.assertEqual(sim.latency["0.3"], 200)
        self.assertEqual(sim.lag["300.0"], 50)
        self.assertEqual(sim.probe_success, 1)

    def test_fault_ratios_are_exact(self):
        sim = demo_app.Simulator()
        sim.set_fault({"checkout_errors": "0.25", "checkout_slow": "0.5", "orders_late": "0.1"})
        for _ in range(10):
            sim.tick()
        self.assertEqual(sim.http, {"200": 150, "500": 50})
        self.assertEqual((sim.latency["0.3"], sim.latency["+Inf"]), (100, 200))
        self.assertEqual((sim.lag["300.0"], sim.lag["+Inf"]), (45, 50))

    def test_website_down(self):
        sim = demo_app.Simulator()
        sim.set_fault({"website_down": "1"})
        sim.tick()
        self.assertEqual(sim.probe_success, 0)
        self.assertIn("probe_success 0", sim.metrics("website"))

    def test_bad_faults(self):
        sim = demo_app.Simulator()
        for bad in ({"nope": "1"}, {"checkout_errors": "2"}, {"checkout_errors": "x"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sim.set_fault(bad)

    def test_exposition_format(self):
        sim = demo_app.Simulator()
        sim.tick()
        text = sim.metrics("checkout")
        self.assertIn("# TYPE http_requests_total counter", text)
        self.assertIn('http_request_duration_seconds_bucket{le="0.3"} 20', text)
        self.assertIn('http_request_duration_seconds_bucket{le="+Inf"} 20', text)
        self.assertIn('orders_processing_lag_seconds_bucket{le="300.0"} 5', sim.metrics("orders"))


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim, cls.sink = demo_app.Simulator(), demo_app.AlertSink()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), demo_app.make_handler(cls.sim, cls.sink))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def req(self, path, method="GET", body=None):
        r = urllib.request.Request(self.base + path, method=method, data=body,
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read().decode()

    def test_metrics_fault_and_alert_sink(self):
        self.assertEqual(self.req("/healthz"), (200, "ok\n"))
        code, text = self.req("/metrics/checkout")
        self.assertEqual(code, 200)
        self.assertIn("http_requests_total", text)
        self.assertEqual(self.req("/metrics/nope")[0], 404)
        code, body = self.req("/fault?checkout_errors=0.2", "POST", b"")
        self.assertEqual((code, json.loads(body)["checkout_errors"]), (200, 0.2))
        self.assertEqual(self.req("/fault?checkout_errors=5", "POST", b"")[0], 400)
        payload = {"status": "firing", "groupLabels": {"slo": "availability"},
                   "alerts": [{"labels": {"alertname": "CheckoutApiAvailabilityBurnPage1h"}}]}
        self.assertEqual(self.req("/alerts/pager", "POST", json.dumps(payload).encode())[0], 200)
        self.assertEqual(self.req("/alerts/pager", "POST", b"not json")[0], 400)
        code, body = self.req("/alerts")
        self.assertEqual(json.loads(body)[-1], {"receiver": "pager", "status": "firing",
                                                "alerts": ["CheckoutApiAvailabilityBurnPage1h"],
                                                "groupLabels": {"slo": "availability"}})


if __name__ == "__main__":
    unittest.main()
