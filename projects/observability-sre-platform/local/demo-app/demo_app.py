#!/usr/bin/env python3
"""Synthetic metrics for the local demo stack, plus an Alertmanager webhook sink. Stdlib only.

It simulates the three synthetic services' SLIs as counters (no real traffic):

  GET  /metrics/checkout   http_requests_total{code}, http_request_duration_seconds histogram
  GET  /metrics/orders     orders_processing_lag_seconds histogram
  GET  /metrics/website    probe_success (stands in for a blackbox exporter)
  GET  /fault              current fault settings (JSON)
  POST /fault?checkout_errors=0.2&checkout_slow=0&orders_late=0&website_down=0
                           set fault ratios (0..1); omitted keys are left as they are
  POST /alerts/<receiver>  Alertmanager webhook sink (stand-in for PagerDuty / tickets / heartbeat)
  GET  /alerts             notifications received so far (JSON, newest last)
  GET  /healthz            ok

Counts are deterministic: a fractional accumulator, not random numbers.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

FAULT_KEYS = ("checkout_errors", "checkout_slow", "orders_late", "website_down")
CHECKOUT_RPS = 20
ORDERS_PER_SECOND = 5
MAX_NOTIFICATIONS = 200


class _Split:
    """Split n events per tick into (good, bad) with a carried fractional remainder."""

    def __init__(self) -> None:
        self.carry = 0.0

    def __call__(self, n: int, ratio: float) -> tuple[int, int]:
        self.carry += n * ratio
        bad = min(n, int(self.carry))
        self.carry -= bad
        return n - bad, bad


class Simulator:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.fault = {k: 0.0 for k in FAULT_KEYS}
        self.http = {"200": 0, "500": 0}
        self.latency = {"0.1": 0, "0.3": 0, "1.0": 0, "+Inf": 0}
        self.latency_sum = 0.0
        self.lag = {"60.0": 0, "300.0": 0, "900.0": 0, "+Inf": 0}
        self.lag_sum = 0.0
        self.probe_success = 1
        self._err, self._slow, self._late, self._down = _Split(), _Split(), _Split(), _Split()

    def set_fault(self, values: dict[str, str]) -> dict[str, float]:
        parsed = {}
        for key, raw in values.items():
            if key not in FAULT_KEYS:
                raise ValueError(f"unknown fault {key!r}; known: {', '.join(FAULT_KEYS)}")
            value = float(raw)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{key} must be between 0 and 1, got {value}")
            parsed[key] = value
        with self.lock:
            self.fault.update(parsed)
            return dict(self.fault)

    def tick(self) -> None:
        """One simulated second."""
        with self.lock:
            ok, failed = self._err(CHECKOUT_RPS, self.fault["checkout_errors"])
            self.http["200"] += ok
            self.http["500"] += failed
            fast, slow = self._slow(CHECKOUT_RPS, self.fault["checkout_slow"])
            for le in ("0.1", "0.3"):
                self.latency[le] += fast
            self.latency["1.0"] += CHECKOUT_RPS
            self.latency["+Inf"] += CHECKOUT_RPS
            self.latency_sum += fast * 0.05 + slow * 0.6
            on_time, late = self._late(ORDERS_PER_SECOND, self.fault["orders_late"])
            for le in ("60.0", "300.0"):
                self.lag[le] += on_time
            self.lag["900.0"] += ORDERS_PER_SECOND
            self.lag["+Inf"] += ORDERS_PER_SECOND
            self.lag_sum += on_time * 20 + late * 600
            up, down = self._down(1, self.fault["website_down"])
            self.probe_success = 0 if down else 1

    def metrics(self, target: str) -> str:
        with self.lock:
            if target == "checkout":
                lines = ["# HELP http_requests_total Synthetic checkout requests by status code.",
                         "# TYPE http_requests_total counter"]
                lines += [f'http_requests_total{{code="{c}",route="/checkout"}} {n}' for c, n in self.http.items()]
                lines += ["# HELP http_request_duration_seconds Synthetic checkout latency.",
                          "# TYPE http_request_duration_seconds histogram"]
                lines += [f'http_request_duration_seconds_bucket{{le="{le}"}} {n}' for le, n in self.latency.items()]
                lines += [f"http_request_duration_seconds_sum {self.latency_sum:.3f}",
                          f"http_request_duration_seconds_count {self.latency['+Inf']}"]
            elif target == "orders":
                lines = ["# HELP orders_processing_lag_seconds Synthetic time from enqueue to processed.",
                         "# TYPE orders_processing_lag_seconds histogram"]
                lines += [f'orders_processing_lag_seconds_bucket{{le="{le}"}} {n}' for le, n in self.lag.items()]
                lines += [f"orders_processing_lag_seconds_sum {self.lag_sum:.3f}",
                          f"orders_processing_lag_seconds_count {self.lag['+Inf']}"]
            elif target == "website":
                lines = ["# HELP probe_success Synthetic probe result for https://www.example.com.",
                         "# TYPE probe_success gauge",
                         f"probe_success {self.probe_success}"]
            else:
                raise KeyError(target)
        return "\n".join(lines) + "\n"


class AlertSink:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.received: list[dict] = []

    def record(self, receiver: str, payload: dict) -> dict:
        entry = {
            "receiver": receiver,
            "status": payload.get("status"),
            "alerts": sorted({a.get("labels", {}).get("alertname", "?") for a in payload.get("alerts", [])}),
            "groupLabels": payload.get("groupLabels", {}),
        }
        with self.lock:
            self.received.append(entry)
            del self.received[:-MAX_NOTIFICATIONS]
        return entry

    def all(self) -> list[dict]:
        with self.lock:
            return list(self.received)


def make_handler(sim: Simulator, sink: AlertSink):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: str, ctype: str = "application/json") -> None:
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            path = urlparse(self.path).path
            if path.startswith("/metrics/"):
                try:
                    self._send(200, sim.metrics(path.split("/", 2)[2]), "text/plain; version=0.0.4")
                except KeyError:
                    self._send(404, json.dumps({"error": "unknown metrics target"}))
            elif path == "/fault":
                with sim.lock:
                    self._send(200, json.dumps(sim.fault, sort_keys=True))
            elif path == "/alerts":
                self._send(200, json.dumps(sink.all(), indent=2))
            elif path == "/healthz":
                self._send(200, "ok\n", "text/plain")
            else:
                self._send(404, json.dumps({"error": "not found"}))

        def do_POST(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            if url.path == "/fault":
                try:
                    values = {k: v[-1] for k, v in parse_qs(url.query).items()}
                    self._send(200, json.dumps(sim.set_fault(values), sort_keys=True))
                except ValueError as exc:
                    self._send(400, json.dumps({"error": str(exc)}))
            elif url.path.startswith("/alerts/"):
                try:
                    payload = json.loads(body or b"{}")
                except json.JSONDecodeError:
                    self._send(400, json.dumps({"error": "body is not JSON"}))
                    return
                entry = sink.record(url.path.split("/", 2)[2], payload)
                print(f"alert notification: {json.dumps(entry, sort_keys=True)}", flush=True)
                self._send(200, json.dumps({"ok": True}))
            else:
                self._send(404, json.dumps({"error": "not found"}))

        def log_message(self, fmt: str, *args) -> None:  # keep scrape noise out of the logs
            return

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1", help="bind address (the compose file uses 0.0.0.0)")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args(argv)
    sim, sink = Simulator(), AlertSink()

    def loop() -> None:
        while True:
            sim.tick()
            time.sleep(1)

    threading.Thread(target=loop, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(sim, sink))
    print(f"demo-app listening on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
