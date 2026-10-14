"""Tiny stdlib HTTP service for the blue/green deployment demo.

Endpoints:
  GET /healthz  -> {"status": "ok"}; the ALB target-group health check
  GET /version  -> {"version", "image_tag", "app_env"}; the lifecycle hooks
                   compare image_tag with the tag being deployed

Configuration is environment variables only: PORT, APP_VERSION, IMAGE_TAG
(set from the image reference by scripts/render_appspec.py), APP_ENV, and
DB_PASSWORD (injected by ECS from Secrets Manager; never logged or returned,
only whether it is present).
"""

from __future__ import annotations

import json
import os
import signal
import socketserver
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping


@dataclass(frozen=True)
class Config:
    port: int
    version: str
    image_tag: str
    app_env: str
    db_password: str | None = field(default=None, repr=False)


def load_config(environ: Mapping[str, str] | None = None) -> Config:
    env = os.environ if environ is None else environ
    raw = env.get("PORT", "8080")
    if not raw.isdigit() or not 0 <= int(raw) <= 65535:
        raise ValueError(f"PORT must be an integer between 0 and 65535, got {raw!r}")
    return Config(
        port=int(raw),
        version=env.get("APP_VERSION", "0.0.0-dev"),
        image_tag=env.get("IMAGE_TAG", "unknown"),
        app_env=env.get("APP_ENV", "local"),
        db_password=env.get("DB_PASSWORD") or None,
    )


def log(message: str, **fields: object) -> None:
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "msg": message, **fields}
    print(json.dumps(record, sort_keys=True), flush=True)


def make_handler(config: Config):
    class Handler(BaseHTTPRequestHandler):
        server_version = "bluegreen-demo"
        sys_version = ""

        def _json(self, status: int, body: dict) -> None:
            data = json.dumps(body, sort_keys=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._json(200, {"status": "ok"})
            elif path == "/version":
                self._json(200, {"version": config.version, "image_tag": config.image_tag,
                                 "app_env": config.app_env, "db_password_loaded": bool(config.db_password)})
            else:
                self._json(404, {"error": "not found"})

        do_HEAD = do_GET

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            # Path without the query string, never the raw request line.
            status = args[1] if len(args) == 3 else None
            status = int(status) if str(status).isdigit() else status
            log("request", method=self.command, path=(self.path or "").split("?", 1)[0], status=status)

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        # Skip the reverse-DNS lookup HTTPServer.server_bind does.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = str(self.server_address[0]), self.server_address[1]


def make_server(config: Config, host: str = "0.0.0.0", port: int | None = None) -> Server:
    return Server((host, config.port if port is None else port), make_handler(config))


def main() -> int:
    try:
        config = load_config()
    except ValueError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    server = make_server(config)

    def on_sigterm(signum, frame) -> None:
        # ECS sends SIGTERM when CodeDeploy drains the old task set.
        log("sigterm_received")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, on_sigterm)
    log("listening", port=server.server_address[1], version=config.version,
        image_tag=config.image_tag, app_env=config.app_env)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
