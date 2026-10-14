"""Tiny stdlib HTTP service deployed by the container delivery pipeline.

Endpoints:
  GET /healthz  -> liveness plus whether the DB secret was injected
  GET /version  -> APP_VERSION and GIT_SHA baked into the image

Configuration comes from environment variables only. DB_PASSWORD is injected
by ECS from Secrets Manager (task definition `secrets`). Its value is never
logged, never returned, and never part of a repr: a logging filter also
redacts it from any record that would contain it by accident.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socketserver
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping

LOGGER_NAME = "app"
REDACTED = "***"


@dataclass(frozen=True)
class Config:
    app_version: str
    git_sha: str
    app_env: str
    port: int
    require_db_password: bool
    db_password: str | None = field(default=None, repr=False)

    @property
    def db_password_loaded(self) -> bool:
        return bool(self.db_password)

    @property
    def db_password_looks_like_json(self) -> bool:
        """True when the whole JSON secret was injected instead of one key.

        That happens when a secret reference omits the `:json-key` suffix
        (see docs/troubleshooting.md). Only the shape is inspected.
        """
        value = (self.db_password or "").strip()
        return value.startswith("{") and value.endswith("}")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def load_config(environ: Mapping[str, str] | None = None) -> Config:
    env = os.environ if environ is None else environ
    port_raw = env.get("PORT", "8080")
    try:
        port = int(port_raw)
    except ValueError:
        raise ValueError(f"PORT must be an integer, got {port_raw!r}") from None
    if not 0 <= port <= 65535:
        raise ValueError(f"PORT must be between 0 and 65535, got {port}")
    return Config(
        app_version=env.get("APP_VERSION", "0.0.0-dev"),
        git_sha=env.get("GIT_SHA", "unknown"),
        app_env=env.get("APP_ENV", "local"),
        port=port,
        require_db_password=_truthy(env.get("REQUIRE_DB_PASSWORD")),
        db_password=env.get("DB_PASSWORD") or None,
    )


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with any `extra={"fields": {...}}` merged in."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, sort_keys=True, default=str)


class RedactSecretFilter(logging.Filter):
    """Defence in depth: replace the secret value anywhere in a record."""

    def __init__(self, secret: str | None) -> None:
        super().__init__()
        self._secret = secret or ""

    def _scrub(self, value: object) -> object:
        if isinstance(value, str) and self._secret and self._secret in value:
            return value.replace(self._secret, REDACTED)
        if isinstance(value, dict):
            return {k: self._scrub(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return type(value)(self._scrub(v) for v in value)
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secret:
            return True
        record.msg = self._scrub(str(record.msg))
        if record.args:
            record.msg = self._scrub(record.msg % record.args)
            record.args = None
        fields = getattr(record, "fields", None)
        if fields is not None:
            record.fields = self._scrub(fields)
        return True


def configure_logging(config: Config, stream=None) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.filters.clear()
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.addFilter(RedactSecretFilter(config.db_password))
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def startup_problems(config: Config) -> list[str]:
    """Reasons the service should refuse to start. Never includes the value."""
    problems = []
    if config.require_db_password and not config.db_password_loaded:
        problems.append("DB_PASSWORD is required but not set (check the task definition secrets)")
    if config.require_db_password and config.db_password_looks_like_json:
        problems.append(
            "DB_PASSWORD looks like a whole JSON document; the secret reference "
            "is probably missing its :json-key suffix"
        )
    return problems


def log_startup(config: Config, logger: logging.Logger) -> None:
    logger.info(
        "starting",
        extra={
            "fields": {
                "app_version": config.app_version,
                "git_sha": config.git_sha,
                "app_env": config.app_env,
                "port": config.port,
                "db_password_loaded": config.db_password_loaded,
                "config": repr(config),
            }
        },
    )
    if config.db_password_looks_like_json:
        logger.warning(
            "db_password_shape_suspicious",
            extra={"fields": {"hint": "secret reference may be missing :json-key"}},
        )


def make_handler(config: Config, logger: logging.Logger):
    class Handler(BaseHTTPRequestHandler):
        server_version = "container-delivery-demo"
        sys_version = ""

        def _send_json(self, status: int, body: dict) -> None:
            data = json.dumps(body, sort_keys=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 (http.server naming)
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "app_env": config.app_env,
                        "db_password_loaded": config.db_password_loaded,
                    },
                )
            elif path == "/version":
                self._send_json(200, {"version": config.app_version, "git_sha": config.git_sha})
            else:
                self._send_json(404, {"error": "not found"})

        do_HEAD = do_GET

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            # Access log with method, path and status only: never the raw
            # request line, which carries query strings.
            fields = {
                "client": self.client_address[0],
                "method": getattr(self, "command", None),
                "path": (getattr(self, "path", "") or "").split("?", 1)[0],
            }
            if format == '"%s" %s %s' and len(args) == 3:
                fields["status"] = int(args[1]) if str(args[1]).isdigit() else str(args[1])
                logger.info("request", extra={"fields": fields})
            else:
                fields["status"] = args[0] if args and isinstance(args[0], int) else None
                logger.warning("request_error", extra={"fields": fields})

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        # HTTPServer.server_bind resolves the FQDN of the bind address, which
        # can stall for seconds without working reverse DNS. Skip it.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


def make_server(config: Config, logger: logging.Logger, host: str = "0.0.0.0", port: int | None = None) -> Server:
    bind_port = config.port if port is None else port
    return Server((host, bind_port), make_handler(config, logger))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=None, help="overrides PORT")
    args = parser.parse_args(argv)

    try:
        config = load_config()
    except ValueError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    logger = configure_logging(config)
    problems = startup_problems(config)
    if problems:
        for problem in problems:
            logger.error("startup_refused", extra={"fields": {"reason": problem}})
        return 2
    log_startup(config, logger)

    server = make_server(config, logger, args.host, args.port)

    def handle_sigterm(signum, frame) -> None:
        # ECS sends SIGTERM, then SIGKILL after stopTimeout. shutdown() must
        # run off the serving thread or it deadlocks.
        logger.info("sigterm_received")
        threading.Thread(target=server.shutdown, daemon=True).start()

    # Install the handler before announcing readiness, so a SIGTERM that
    # arrives right after "listening" still stops the server cleanly.
    signal.signal(signal.SIGTERM, handle_sigterm)
    logger.info("listening", extra={"fields": {"address": f"{args.host}:{server.server_address[1]}"}})
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        logger.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
