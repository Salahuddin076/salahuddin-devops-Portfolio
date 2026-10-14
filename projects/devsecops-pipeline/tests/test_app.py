import json
import threading
import unittest
import urllib.error
import urllib.request

import helpers  # noqa: F401
import server


class RouteTests(unittest.TestCase):
    def test_routes(self):
        self.assertEqual(server.route("/")[0], 200)
        self.assertEqual(json.loads(server.route("/healthz")[2]), {"status": "ok"})
        self.assertEqual(server.route("/nope")[0], 404)
        self.assertEqual(server.route("/healthz?x=1")[0], 200)

    def test_version_from_env(self):
        body = json.loads(server.route("/version", {"APP_VERSION": "1.2.3", "GIT_SHA": "abc"})[2])
        self.assertEqual(body, {"version": "1.2.3", "revision": "abc"})


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._log = server.Handler.log_message
        server.Handler.log_message = lambda *args: None  # quiet test output
        cls.httpd = server.make_server(0, host="127.0.0.1")
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.Handler.log_message = cls._log

    def get(self, path):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5)

    def test_security_headers_on_every_response(self):
        with self.get("/") as resp:
            for name, value in server.SECURITY_HEADERS.items():
                self.assertEqual(resp.headers[name], value, name)

    def test_server_header_does_not_leak_python_version(self):
        with self.get("/healthz") as resp:
            self.assertNotIn("Python", resp.headers["Server"])

    def test_404_also_has_headers(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/missing")
        self.assertEqual(ctx.exception.code, 404)
        self.assertEqual(ctx.exception.headers["X-Content-Type-Options"], "nosniff")
        ctx.exception.close()


if __name__ == "__main__":
    unittest.main()
