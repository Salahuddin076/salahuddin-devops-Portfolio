"""orders-api over real HTTP on an ephemeral port (stdlib only)."""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import orders_api  # noqa: E402


class OrdersApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = orders_api.make_server("127.0.0.1", 0, version="v1.2.3-abc1234", ready=True)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read().decode()

    def post(self, path, body: bytes):
        req = urllib.request.Request(self.base + path, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read().decode()

    def test_health_ready_version(self):
        self.assertEqual(self.get("/healthz")[0], 200)
        self.assertEqual(self.get("/readyz"), (200, '{"ready": true}'))
        self.assertEqual(json.loads(self.get("/version")[1]), {"version": "v1.2.3-abc1234"})

    def test_orders(self):
        code, body = self.get("/orders/ord-42")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["id"], "ord-42")
        code, body = self.post("/orders", json.dumps({"items": [{"sku": "SKU-9", "qty": 2}]}).encode())
        self.assertEqual(code, 201)
        self.assertEqual(json.loads(body)["items"][0]["sku"], "SKU-9")
        self.assertEqual(self.post("/orders", b'{"items": []}')[0], 400)
        self.assertEqual(self.post("/orders", b"not json")[0], 400)
        self.assertEqual(self.get("/nope")[0], 404)

    def test_metrics_count_codes_with_bounded_routes(self):
        self.get("/orders/a1")
        self.get("/orders/b2")
        _, text = self.get("/metrics")
        self.assertIn("# TYPE http_requests_total counter", text)
        self.assertRegex(text, r'http_requests_total\{method="GET",path="/orders/:id",code="200"\} [2-9]')
        self.assertNotIn("/orders/a1", text)

    def test_not_ready_without_config(self):
        server = orders_api.make_server("127.0.0.1", 0, version="x", ready=False)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            port = server.server_address[1]
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=5)
            self.assertEqual(ctx.exception.code, 503)
            ctx.exception.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
