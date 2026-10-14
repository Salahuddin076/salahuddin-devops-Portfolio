"""Smoke checks and the real urllib client against a local HTTP server."""

import threading
import unittest

from helpers import TAG, FakeHttp

import server
from smoke import SmokeConfig, UrllibClient, p95, run_smoke


class P95Tests(unittest.TestCase):
    def test_nearest_rank(self):
        self.assertEqual(p95([5.0]), 5.0)
        self.assertEqual(p95(list(range(1, 21))), 19)
        self.assertEqual(p95(list(range(1, 101))), 95)
        with self.assertRaises(ValueError):
            p95([])


class SmokeConfigTests(unittest.TestCase):
    def test_rejects_bad_inputs(self):
        for kwargs in ({"base_url": "ftp://x"}, {"expected_tag": ""}, {"requests": 0}, {"p95_budget_ms": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SmokeConfig(**{"base_url": "https://api.example.com", "expected_tag": TAG, **kwargs})


class RunSmokeTests(unittest.TestCase):
    def test_non_200_latency_samples_fail(self):
        class Flaky(FakeHttp):
            def get(self, url, timeout):
                response = super().get(url, timeout)
                if len(self.calls) == 5:
                    return type(response)(502, b"", response.elapsed_seconds)
                return response

        cfg = SmokeConfig(base_url="https://api.example.com", expected_tag=TAG, requests=5)
        result = run_smoke(cfg, Flaky())
        self.assertFalse(result.ok)
        self.assertIn("1/5 latency-sample requests were not 200", result.failures)


class UrllibClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = server.load_config({"IMAGE_TAG": TAG, "APP_VERSION": "1.0.0"})
        cls.httpd = server.make_server(config, host="127.0.0.1", port=0)
        cls._log = server.log
        server.log = lambda *a, **k: None  # keep test output quiet
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.log = cls._log

    def test_end_to_end_against_the_app(self):
        cfg = SmokeConfig(base_url=self.base, expected_tag=TAG, requests=5, p95_budget_ms=2000)
        result = run_smoke(cfg, UrllibClient())
        self.assertTrue(result.ok, result.failures)
        self.assertEqual(result.samples, 5)

    def test_http_error_status_is_returned_not_raised(self):
        response = UrllibClient().get(self.base + "/missing", 2)
        self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
