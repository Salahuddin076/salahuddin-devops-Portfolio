"""The demo service over real HTTP on an ephemeral port."""

import json
import threading
import unittest
import urllib.error
import urllib.request

import helpers  # noqa: F401  (sets sys.path)
import server


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._log = server.log
        server.log = lambda *a, **k: None
        config = server.load_config({"IMAGE_TAG": "abc123", "APP_VERSION": "1.0.0", "APP_ENV": "dev",
                                     "DB_PASSWORD": "sentinel-not-a-secret"})
        cls.httpd = server.make_server(config, host="127.0.0.1", port=0)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.log = cls._log

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read().decode()

    def test_health(self):
        self.assertEqual(self.get("/healthz"), (200, '{"status": "ok"}'))

    def test_version_reports_image_tag_not_secret(self):
        status, body = self.get("/version?x=1")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual((data["image_tag"], data["version"], data["app_env"]), ("abc123", "1.0.0", "dev"))
        self.assertTrue(data["db_password_loaded"])
        self.assertNotIn("sentinel-not-a-secret", body)

    def test_unknown_path_404(self):
        self.assertEqual(self.get("/nope")[0], 404)

    def test_config_validation(self):
        with self.assertRaises(ValueError):
            server.load_config({"PORT": "http"})
        self.assertNotIn("sentinel", repr(server.load_config({"DB_PASSWORD": "sentinel"})))


if __name__ == "__main__":
    unittest.main()
