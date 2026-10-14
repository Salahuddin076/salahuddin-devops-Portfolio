"""The app: loading from files, rotation pickup, and no secret value in logs or /healthz."""

from __future__ import annotations

import io
import json
import logging
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from helpers import APP_DIR, write_secrets

import server

def make_values(tag):
    """Random per run, so no credential-shaped literal sits in this file."""
    return {"db-username": f"app_{tag}", "db-password": secrets.token_urlsafe(18),
            "db-host": f"db-{tag}.example.com", "api-key": secrets.token_hex(16)}


V1, V2 = make_values("v1"), make_values("v2")


class TempSecrets(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "secrets"
        self.addCleanup(self._tmp.cleanup)
        # Quiet by default; LoggingTests installs its own capturing handler.
        saved = (server.log.handlers[:], server.log.propagate)
        server.log.handlers[:] = [logging.NullHandler()]
        server.log.propagate = False

        def restore():
            server.log.handlers[:], server.log.propagate = saved
        self.addCleanup(restore)


class SecretStoreTests(TempSecrets):
    def test_loads_all_required_files(self):
        write_secrets(self.dir, V1)
        store = server.SecretStore(str(self.dir))
        self.assertTrue(store.refresh())
        self.assertEqual(store.get("db-password"), V1["db-password"])
        h = store.health()
        self.assertTrue(h["secrets_loaded"])
        self.assertEqual(h["missing"], [])
        self.assertEqual(h["version"], server.fingerprint(V1))

    def test_strips_trailing_newline(self):
        self.dir.mkdir()
        for name, value in V1.items():
            (self.dir / name).write_text(value + "\n")
        store = server.SecretStore(str(self.dir))
        store.refresh()
        self.assertEqual(store.get("api-key"), V1["api-key"])

    def test_missing_and_empty_files_are_reported_not_loaded(self):
        self.dir.mkdir()
        (self.dir / "db-username").write_text("app")
        (self.dir / "db-password").write_text("   ")
        store = server.SecretStore(str(self.dir))
        store.refresh()
        h = store.health()
        self.assertFalse(h["secrets_loaded"])
        self.assertEqual(h["missing"], ["db-password", "db-host", "api-key"])
        self.assertIsNone(h["version"])

    def test_nonexistent_directory_is_not_an_error(self):
        store = server.SecretStore(str(self.dir / "nope"))
        store.refresh()
        self.assertFalse(store.health()["secrets_loaded"])

    def test_rotation_is_picked_up_without_restart(self):
        write_secrets(self.dir, V1)
        store = server.SecretStore(str(self.dir))
        store.refresh()
        self.assertFalse(store.refresh(), "no change on disk, no reload")
        write_secrets(self.dir, V2)
        self.assertTrue(store.refresh())
        self.assertEqual(store.get("db-password"), V2["db-password"])
        self.assertEqual(store.health()["version"], server.fingerprint(V2))
        self.assertEqual(store.health()["rotations"], 1)

    def test_watcher_thread_reloads(self):
        write_secrets(self.dir, V1)
        store = server.SecretStore(str(self.dir))
        store.refresh()
        watcher = server.Watcher(store, 0.05)
        watcher.start()
        self.addCleanup(watcher.stop_event.set)
        write_secrets(self.dir, V2)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and store.get("api-key") != V2["api-key"]:
            time.sleep(0.02)
        self.assertEqual(store.get("api-key"), V2["api-key"])

    def test_fingerprint_is_stable_order_independent_and_not_the_value(self):
        fp = server.fingerprint(V1)
        self.assertEqual(fp, server.fingerprint(dict(reversed(list(V1.items())))))
        self.assertNotEqual(fp, server.fingerprint(V2))
        self.assertEqual(len(fp), 16)
        for value in V1.values():
            self.assertNotIn(value, fp)

    def test_settings_defaults_and_validation(self):
        cfg = server.settings({})
        self.assertEqual(cfg["directory"], "/mnt/secrets")
        self.assertEqual(cfg["required"], server.DEFAULT_REQUIRED)
        self.assertEqual(server.settings({"SECRETS_REQUIRED": "a, b,"})["required"], ("a", "b"))
        with self.assertRaises(ValueError):
            server.settings({"SECRETS_POLL_SECONDS": "0"})


class LoggingTests(TempSecrets):
    def _capture(self, store):
        stream = io.StringIO()
        server.configure_logging(store, "DEBUG")
        server.log.handlers[0].stream = stream
        return stream

    def test_load_and_rotation_logs_carry_names_and_versions_only(self):
        write_secrets(self.dir, V1)
        store = server.SecretStore(str(self.dir))
        stream = self._capture(store)
        store.refresh()
        write_secrets(self.dir, V2)
        store.refresh()
        out = stream.getvalue()
        self.assertIn("secrets loaded: names=api-key,db-host,db-password,db-username", out)
        self.assertIn(f"secrets rotated: version {server.fingerprint(V1)} -> {server.fingerprint(V2)}", out)
        for value in list(V1.values()) + list(V2.values()):
            self.assertNotIn(value, out)

    def test_redacting_filter_catches_a_careless_log_call(self):
        write_secrets(self.dir, V1)
        store = server.SecretStore(str(self.dir))
        stream = self._capture(store)
        store.refresh()
        server.log.error("connect failed for %s with %s", store.get("db-username"), store.get("db-password"))
        server.log.info("header Authorization: Bearer " + store.get("api-key"))
        out = stream.getvalue()
        self.assertNotIn(V1["db-password"], out)
        self.assertNotIn(V1["api-key"], out)
        self.assertEqual(out.count(server.REDACTED), 3)


class HttpTests(TempSecrets):
    def start(self, store):
        httpd = server.Server(("127.0.0.1", 0), server.make_handler(store))
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return httpd.server_address[1]

    def get(self, port, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read().decode()

    def test_healthz_reports_loaded_without_values(self):
        write_secrets(self.dir, V1)
        store = server.SecretStore(str(self.dir))
        store.refresh()
        port = self.start(store)
        status, body = self.get(port, "/healthz")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(set(data), {"status", "secrets_loaded", "secret_names", "missing", "version", "rotations"})
        self.assertTrue(data["secrets_loaded"])
        for value in V1.values():
            self.assertNotIn(value, body)
        _, page = self.get(port, "/")
        for value in V1.values():
            self.assertNotIn(value, page)

    def test_healthz_503_when_secrets_missing_livez_still_200(self):
        store = server.SecretStore(str(self.dir))
        store.refresh()
        port = self.start(store)
        status, body = self.get(port, "/healthz")
        self.assertEqual(status, 503)
        self.assertFalse(json.loads(body)["secrets_loaded"])
        self.assertEqual(self.get(port, "/livez")[0], 200)
        self.assertEqual(self.get(port, "/nope")[0], 404)


class ProcessTests(TempSecrets):
    def test_real_process_never_writes_a_value_to_its_output(self):
        write_secrets(self.dir, V1)
        env = {"PATH": os.environ.get("PATH", ""), "SECRETS_DIR": str(self.dir), "PORT": "0",
               "SECRETS_POLL_SECONDS": "0.1", "LOG_LEVEL": "DEBUG"}
        proc = subprocess.Popen([sys.executable, str(APP_DIR / "server.py")], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            time.sleep(0.5)
            write_secrets(self.dir, V2)
            time.sleep(0.6)
        finally:
            proc.terminate()
            out, _ = proc.communicate(timeout=5)
        self.assertIn("secrets loaded", out)
        self.assertIn("secrets rotated", out)
        for value in list(V1.values()) + list(V2.values()):
            self.assertNotIn(value, out)


if __name__ == "__main__":
    unittest.main()
