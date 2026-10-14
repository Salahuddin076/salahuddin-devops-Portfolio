import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

import helpers

import server

SENTINEL = "s3ntinel-Pa55word-do-not-log-7f3a"


class RunningServer:
    """Start the real HTTP server on an ephemeral port, capturing its logs."""

    def __init__(self, environ):
        self.config = server.load_config(environ)
        self.stream = io.StringIO()
        self.logger = server.configure_logging(self.config, self.stream)
        self.httpd = server.make_server(self.config, self.logger, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        server.log_startup(self.config, self.logger)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def url(self, path):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"

    def get(self, path):
        try:
            with urllib.request.urlopen(self.url(path), timeout=5) as response:
                return response.status, response.headers, response.read().decode()
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.headers, err.read().decode()

    def log_lines(self):
        return [json.loads(line) for line in self.stream.getvalue().splitlines() if line.strip()]


BASE_ENV = {"APP_VERSION": "1.4.2", "GIT_SHA": "a" * 40, "APP_ENV": "staging", "PORT": "8080"}


class HealthAndVersionTests(unittest.TestCase):
    def test_healthz_ok(self):
        with RunningServer({**BASE_ENV, "DB_PASSWORD": SENTINEL}) as srv:
            status, headers, body = srv.get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(json.loads(body), {"status": "ok", "app_env": "staging", "db_password_loaded": True})

    def test_healthz_reports_missing_secret_without_failing(self):
        with RunningServer(BASE_ENV) as srv:
            status, _, body = srv.get("/healthz")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["db_password_loaded"])

    def test_version_reads_env(self):
        with RunningServer(BASE_ENV) as srv:
            status, _, body = srv.get("/version")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"version": "1.4.2", "git_sha": "a" * 40})

    def test_version_defaults(self):
        config = server.load_config({})
        self.assertEqual((config.app_version, config.git_sha, config.port), ("0.0.0-dev", "unknown", 8080))

    def test_query_string_ignored_and_unknown_path_404(self):
        with RunningServer(BASE_ENV) as srv:
            self.assertEqual(srv.get("/healthz?verbose=1")[0], 200)
            status, _, body = srv.get("/admin")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {"error": "not found"})

    def test_access_log_is_json_without_query_string(self):
        with RunningServer(BASE_ENV) as srv:
            srv.get("/version?token=abc123")
            time.sleep(0.05)
            lines = srv.log_lines()
        requests = [l for l in lines if l["message"] == "request"]
        self.assertTrue(requests)
        self.assertEqual(requests[-1]["path"], "/version")
        self.assertEqual(requests[-1]["status"], 200)
        self.assertNotIn("abc123", json.dumps(requests[-1]))

    def test_invalid_port_rejected(self):
        with self.assertRaises(ValueError):
            server.load_config({"PORT": "eighty"})
        with self.assertRaises(ValueError):
            server.load_config({"PORT": "70000"})


class SecretNeverLoggedTests(unittest.TestCase):
    def test_secret_absent_from_logs_and_responses(self):
        with RunningServer({**BASE_ENV, "DB_PASSWORD": SENTINEL}) as srv:
            bodies = [srv.get(p)[2] for p in ("/healthz", "/version", "/missing", "/healthz?x=1")]
            time.sleep(0.05)
            logs = srv.stream.getvalue()
        self.assertIn('"message": "starting"', logs)
        self.assertIn('"db_password_loaded": true', logs)
        self.assertNotIn(SENTINEL, logs)
        for body in bodies:
            self.assertNotIn(SENTINEL, body)

    def test_secret_not_in_repr_or_str(self):
        config = server.load_config({"DB_PASSWORD": SENTINEL})
        self.assertNotIn(SENTINEL, repr(config))
        self.assertNotIn(SENTINEL, str(config))
        self.assertTrue(config.db_password_loaded)

    def test_filter_redacts_accidental_logging(self):
        config = server.load_config({"DB_PASSWORD": SENTINEL})
        stream = io.StringIO()
        logger = server.configure_logging(config, stream)
        logger.info("connecting with %s", SENTINEL)
        logger.info("dsn=postgres://app:" + SENTINEL + "@db")
        logger.info("fields", extra={"fields": {"password": SENTINEL, "nested": {"p": [SENTINEL]}}})
        output = stream.getvalue()
        self.assertNotIn(SENTINEL, output)
        self.assertEqual(output.count(server.REDACTED), 4)

    def test_secret_absent_from_process_output(self):
        """Run the real entrypoint as a subprocess and read stdout/stderr."""
        env = {**os.environ, **BASE_ENV, "DB_PASSWORD": SENTINEL, "PORT": "0", "REQUIRE_DB_PASSWORD": "true"}
        proc = subprocess.Popen(
            [sys.executable, os.path.join(helpers.APP_DIR, "server.py"), "--host", "127.0.0.1"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            first = proc.stdout.readline()
            second = proc.stdout.readline()
        finally:
            proc.terminate()
            rest, _ = proc.communicate(timeout=5)
        output = first + second + rest
        self.assertIn('"message": "listening"', output)
        self.assertIn('"message": "stopped"', output, "SIGTERM should stop the server cleanly")
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn(SENTINEL, output)


class StartupChecksTests(unittest.TestCase):
    def test_required_secret_missing_refuses_to_start(self):
        config = server.load_config({"REQUIRE_DB_PASSWORD": "true"})
        self.assertEqual(len(server.startup_problems(config)), 1)

    def test_whole_json_blob_detected_without_logging_it(self):
        blob = json.dumps({"username": "app", "password": SENTINEL})
        config = server.load_config({"REQUIRE_DB_PASSWORD": "true", "DB_PASSWORD": blob})
        problems = server.startup_problems(config)
        self.assertTrue(any(":json-key" in p for p in problems))
        stream = io.StringIO()
        server.log_startup(config, server.configure_logging(config, stream))
        self.assertIn("db_password_shape_suspicious", stream.getvalue())
        self.assertNotIn(SENTINEL, stream.getvalue())
        self.assertNotIn("username", stream.getvalue())

    def test_entrypoint_exits_2_when_secret_required_and_missing(self):
        env = {k: v for k, v in os.environ.items() if k != "DB_PASSWORD"}
        env.update({"REQUIRE_DB_PASSWORD": "true", "PORT": "0"})
        result = subprocess.run(
            [sys.executable, os.path.join(helpers.APP_DIR, "server.py")],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("startup_refused", result.stdout)

    def test_optional_secret_allows_start(self):
        self.assertEqual(server.startup_problems(server.load_config({})), [])


if __name__ == "__main__":
    unittest.main()
