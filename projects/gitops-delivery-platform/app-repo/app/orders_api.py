#!/usr/bin/env python3
"""orders-api: a tiny synthetic service (stdlib only) that the GitOps flow deploys.

Endpoints:
  GET  /healthz          liveness, always 200
  GET  /readyz           readiness, 503 until the app is configured
  GET  /orders/<id>      a synthetic order
  POST /orders           create a synthetic order (JSON body with "items")
  GET  /version          the image tag the pod runs (APP_VERSION)
  GET  /metrics          Prometheus text: http_requests_total{method,path,code}

The availability SLI used by the canary analysis is the same good/total ratio
as the observability project: requests without a 5xx over all requests.
"""

from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ORDER_PATH = re.compile(r"^/orders/([A-Za-z0-9-]{1,64})$")


class Metrics:
    """Thread-safe request counters, rendered in the Prometheus text format."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, str, str], int] = {}

    def inc(self, method: str, path: str, code: int) -> None:
        key = (method, path, str(code))
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1

    def render(self) -> str:
        lines = ["# HELP http_requests_total HTTP requests by method, route and status code.",
                 "# TYPE http_requests_total counter"]
        with self._lock:
            for (method, path, code), n in sorted(self._counts.items()):
                lines.append(f'http_requests_total{{method="{method}",path="{path}",code="{code}"}} {n}')
        return "\n".join(lines) + "\n"


def route_label(path: str) -> str:
    """Collapse IDs so the metric has bounded cardinality."""
    if ORDER_PATH.match(path):
        return "/orders/:id"
    if path in ("/healthz", "/readyz", "/orders", "/version", "/metrics"):
        return path
    return "other"


def make_order(order_id: str, items: list | None = None) -> dict:
    items = items if items is not None else [{"sku": "SKU-0001", "qty": 1}]
    return {"id": order_id, "status": "created", "items": items, "currency": "USD"}


def build_handler(version: str, ready: bool, metrics: Metrics):
    class Handler(BaseHTTPRequestHandler):
        server_version = "orders-api"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet by default; access logs belong to the ingress
            return

        def _send(self, code: int, body: str, ctype: str = "application/json") -> None:
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            path = self.path.split("?", 1)[0]
            if path != "/metrics":
                metrics.inc(self.command, route_label(path), code)

        def do_GET(self):  # noqa: N802 (http.server naming)
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                return self._send(200, json.dumps({"status": "ok"}))
            if path == "/readyz":
                return self._send(200 if ready else 503, json.dumps({"ready": ready}))
            if path == "/version":
                return self._send(200, json.dumps({"version": version}))
            if path == "/metrics":
                return self._send(200, metrics.render(), "text/plain; version=0.0.4")
            m = ORDER_PATH.match(path)
            if m:
                return self._send(200, json.dumps(make_order(m.group(1))))
            return self._send(404, json.dumps({"error": "not found"}))

        def do_POST(self):  # noqa: N802
            if self.path.split("?", 1)[0] != "/orders":
                return self._send(404, json.dumps({"error": "not found"}))
            length = int(self.headers.get("Content-Length") or 0)
            if length > 64 * 1024:
                return self._send(413, json.dumps({"error": "body too large"}))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                items = body["items"]
                if not isinstance(items, list) or not items:
                    raise ValueError("items must be a non-empty list")
            except (ValueError, KeyError, TypeError) as exc:
                return self._send(400, json.dumps({"error": f"bad request: {exc}"}))
            return self._send(201, json.dumps(make_order("ord-new", items)))

    return Handler


def make_server(host: str = "0.0.0.0", port: int = 8080, version: str | None = None,
                ready: bool | None = None) -> ThreadingHTTPServer:
    version = version if version is not None else os.environ.get("APP_VERSION", "dev")
    if ready is None:
        # Ready only when the secret the ExternalSecret provides is mounted as env.
        ready = bool(os.environ.get("DATABASE_URL")) or os.environ.get("APP_ENV") == "local"
    return ThreadingHTTPServer((host, port), build_handler(version, ready, Metrics()))


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = make_server(port=port)
    print(f"orders-api listening on :{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
