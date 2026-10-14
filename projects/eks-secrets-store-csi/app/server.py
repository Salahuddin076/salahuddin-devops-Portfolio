#!/usr/bin/env python3
"""secure-frontend stand-in: a stdlib HTTP service that reads its secrets from files.

The Secrets Store CSI Driver mounts one file per secret (or per jmesPath key)
under SECRETS_DIR. This service:

- reads the files named in SECRETS_REQUIRED from SECRETS_DIR (never env vars);
- polls the files' stat signature every SECRETS_POLL_SECONDS and re-reads them
  when it changes, so a rotated value is picked up without a restart;
- never logs a secret value: log lines carry secret *names* and a version
  fingerprint only, and a logging filter redacts any loaded value that slips
  into a message anyway;
- serves /healthz (ready when every required secret is loaded, 503 otherwise)
  and /livez (process is up). Neither returns a value.

Environment (none of these is a secret):
  SECRETS_DIR            directory with the mounted files    (default /mnt/secrets)
  SECRETS_REQUIRED       comma-separated file names          (default db-username,db-password,db-host,api-key)
  SECRETS_POLL_SECONDS   how often to check for rotation     (default 10)
  PORT                   listen port                         (default 8080)
  LOG_LEVEL              logging level                       (default INFO)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_REQUIRED = ("db-username", "db-password", "db-host", "api-key")
REDACTED = "[REDACTED]"
MIN_REDACT_LEN = 4  # don't "redact" one-character values out of every log line

log = logging.getLogger("secure-frontend")


def fingerprint(values: dict[str, str]) -> str:
    """A version id for a set of secret values: truncated SHA-256 over name and value.

    All values are hashed together, so the digest always includes the
    high-entropy API key; a weak DB password can't be confirmed by guessing it
    against /healthz. 16 hex characters is plenty to tell versions apart.
    """
    h = hashlib.sha256()
    for name in sorted(values):
        h.update(name.encode())
        h.update(b"\0")
        h.update(values[name].encode())
        h.update(b"\0")
    return h.hexdigest()[:16]


@dataclass
class Snapshot:
    values: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    version: str | None = None
    loaded_at: float | None = None


class SecretStore:
    """Loads required secret files and reloads them when their stat signature changes.

    The driver (like kubelet's projected volumes) updates files through an
    atomic `..data` symlink swap, so os.stat (which follows symlinks) sees a
    new inode and mtime for every file at once.
    """

    def __init__(self, directory: str, required: tuple[str, ...] = DEFAULT_REQUIRED) -> None:
        self.directory = directory
        self.required = tuple(required)
        self._lock = threading.Lock()
        self._signature: tuple | None = None
        self._snapshot = Snapshot(missing=list(self.required))
        self.rotations = 0  # loaded version -> different loaded version

    def _stat_signature(self) -> tuple:
        sig = []
        for name in self.required:
            try:
                st = os.stat(os.path.join(self.directory, name))
                sig.append((name, st.st_ino, st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((name, None, None, None))
        return tuple(sig)

    def _read(self) -> Snapshot:
        values, missing = {}, []
        for name in self.required:
            try:
                with open(os.path.join(self.directory, name), encoding="utf-8") as fh:
                    value = fh.read().strip()
            except OSError:
                missing.append(name)
                continue
            if value:
                values[name] = value
            else:
                missing.append(name)
        snap = Snapshot(values=values, missing=missing, loaded_at=time.time())
        if not missing:
            snap.version = fingerprint(values)
        return snap

    def refresh(self) -> bool:
        """Re-read if anything changed on disk. Returns True when the loaded version changed."""
        sig = self._stat_signature()
        if sig == self._signature:
            return False
        new = self._read()
        with self._lock:
            old = self._snapshot
            self._snapshot = new
            self._signature = sig
        if new.version == old.version and new.missing == old.missing:
            return False
        if new.missing:
            log.warning("secrets incomplete: missing=%s", ",".join(new.missing))
        elif old.version is None:
            log.info("secrets loaded: names=%s version=%s", ",".join(sorted(new.values)), new.version)
        else:
            self.rotations += 1
            log.info("secrets rotated: version %s -> %s", old.version, new.version)
        return True

    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    def get(self, name: str) -> str | None:
        """The current value for application code. Never pass it to a logger."""
        return self.snapshot().values.get(name)

    def known_values(self) -> list[str]:
        return [v for v in self.snapshot().values.values() if len(v) >= MIN_REDACT_LEN]

    def health(self) -> dict:
        snap = self.snapshot()
        return {
            "status": "ok" if not snap.missing else "degraded",
            "secrets_loaded": not snap.missing,
            "secret_names": list(self.required),
            "missing": list(snap.missing),
            "version": snap.version,
            "rotations": self.rotations,
        }


class RedactingFilter(logging.Filter):
    """Defense in depth: replace any currently loaded secret value in a log record."""

    def __init__(self, store: SecretStore) -> None:
        super().__init__()
        self.store = store

    def filter(self, record: logging.LogRecord) -> bool:
        values = self.store.known_values()
        if not values:
            return True
        message = record.getMessage()
        redacted = message
        for value in values:
            redacted = redacted.replace(value, REDACTED)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


class Watcher(threading.Thread):
    def __init__(self, store: SecretStore, interval: float) -> None:
        super().__init__(name="secret-watcher", daemon=True)
        self.store, self.interval = store, interval
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                self.store.refresh()
            except Exception:  # keep watching; never include the exception text (it could echo file content)
                log.error("secret refresh failed; keeping the previous version")


def make_handler(store: SecretStore):
    class Handler(BaseHTTPRequestHandler):
        server_version = "secure-frontend"
        sys_version = ""

        def _send(self, status: int, body: dict | str, content_type: str = "application/json") -> None:
            data = (json.dumps(body, sort_keys=True) if isinstance(body, dict) else body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            path = self.path.split("?", 1)[0]
            if path == "/livez":
                self._send(200, {"status": "alive"})
            elif path == "/healthz":
                h = store.health()
                self._send(200 if h["secrets_loaded"] else 503, h)
            elif path == "/":
                h = store.health()
                page = ("<!doctype html><title>secure-frontend</title>"
                        f"<h1>secure-frontend</h1><p>secrets loaded: {'yes' if h['secrets_loaded'] else 'no'}"
                        f" (version {h['version'] or 'none'})</p>")
                self._send(200, page, "text/html; charset=utf-8")
            else:
                self._send(404, {"error": "not found"})

        def log_message(self, fmt: str, *args) -> None:
            # Path only (query strings can carry user data), via the redacting logger.
            log.info("%s %s %s", self.command, self.path.split("?", 1)[0], args[1] if len(args) > 1 else "-")

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        # HTTPServer.server_bind resolves the FQDN, which can stall for seconds
        # on a host with slow reverse DNS. The name is never used here.
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = "secure-frontend", self.server_address[1]


def configure_logging(store: SecretStore, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter(store))
    log.handlers[:] = [handler]
    log.setLevel(level)
    log.propagate = False


def settings(env: dict[str, str]) -> dict:
    required = tuple(n.strip() for n in env.get("SECRETS_REQUIRED", ",".join(DEFAULT_REQUIRED)).split(",") if n.strip())
    poll = float(env.get("SECRETS_POLL_SECONDS", "10"))
    if poll <= 0:
        raise ValueError("SECRETS_POLL_SECONDS must be > 0")
    return {
        "directory": env.get("SECRETS_DIR", "/mnt/secrets"),
        "required": required,
        "poll": poll,
        "port": int(env.get("PORT", "8080")),
        "log_level": env.get("LOG_LEVEL", "INFO").upper(),
    }


def main(env: dict[str, str] | None = None) -> int:
    cfg = settings(dict(os.environ) if env is None else env)
    store = SecretStore(cfg["directory"], cfg["required"])
    configure_logging(store, cfg["log_level"])
    store.refresh()
    watcher = Watcher(store, cfg["poll"])
    watcher.start()
    server = Server(("0.0.0.0", cfg["port"]), make_handler(store))  # noqa: S104 (container)
    log.info("listening on :%d secrets_dir=%s poll=%ss", server.server_address[1], cfg["directory"], cfg["poll"])

    def shutdown(signum, _frame):
        log.info("signal %d: shutting down", signum)
        watcher.stop_event.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    server.serve_forever()
    server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
