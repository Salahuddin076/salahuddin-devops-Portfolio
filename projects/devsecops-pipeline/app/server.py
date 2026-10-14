"""Synthetic stdlib HTTP service scanned by the DevSecOps pipeline.

It is deliberately small and clean: the point of the project is the
pipeline around it. It still carries the things the scanners check for:

- no third-party dependencies (nothing for SCA to flag in the real app);
- every response carries the security headers an OWASP ZAP baseline scan
  looks for, and the Server header does not leak the Python version;
- no shell, no eval, no dynamic imports, no secrets (nothing for Semgrep or
  gitleaks to flag).

Endpoints:
  GET /         -> small HTML page
  GET /healthz  -> {"status": "ok"}
  GET /version  -> {"version": APP_VERSION, "revision": GIT_SHA}
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cache-Control": "no-store",
}

INDEX_HTML = (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<title>devsecops demo</title></head>"
    "<body><h1>devsecops demo</h1><p>Synthetic service for the supply-chain pipeline.</p></body></html>"
)


def app_info(environ: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ if environ is None else environ
    return {"version": env.get("APP_VERSION", "0.0.0-dev"), "revision": env.get("GIT_SHA", "unknown")}


def route(path: str, environ: dict[str, str] | None = None) -> tuple[int, str, bytes]:
    """Pure routing function: (status, content type, body). Easy to unit test."""
    path = path.split("?", 1)[0]
    if path == "/":
        return 200, "text/html; charset=utf-8", INDEX_HTML.encode()
    if path == "/healthz":
        return 200, "application/json", json.dumps({"status": "ok"}).encode()
    if path == "/version":
        return 200, "application/json", json.dumps(app_info(environ)).encode()
    return 404, "application/json", json.dumps({"error": "not found"}).encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "app"
    sys_version = ""  # keep the Python version out of the Server header

    def _send(self, status: int, content_type: str, body: bytes, head_only: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        self._send(*route(self.path))

    def do_HEAD(self) -> None:  # noqa: N802
        self._send(*route(self.path), head_only=True)

    def log_message(self, fmt: str, *args) -> None:
        # One line per request on stdout; no headers or bodies are logged.
        sys.stdout.write("%s %s\n" % (self.address_string(), fmt % args))


def make_server(port: int, host: str = "0.0.0.0") -> ThreadingHTTPServer:  # nosec B104: container listens on all interfaces
    return ThreadingHTTPServer((host, port), Handler)


def main() -> int:
    port = int(os.environ.get("PORT", "8080"))
    server = make_server(port)

    def _stop(signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print(f"listening on :{port}", flush=True)
    server.serve_forever()
    server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
