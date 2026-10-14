"""HTTP smoke checks shared by the CodeDeploy lifecycle hooks (stdlib only).

Three checks against one base URL:
  1. GET <health_path> returns 200;
  2. GET <version_path> returns 200 and JSON whose `image_tag` equals the
     tag being deployed;
  3. N further GETs of <health_path> all return 200 and their p95 latency
     (nearest-rank) is within the budget.

The HTTP client is injected, so tests use a fake. The real client is
`UrllibClient`. A time budget (`remaining_ms`, normally the Lambda context's
`get_remaining_time_in_millis`) stops the checks before the Lambda would be
killed, so the hook can still report Failed instead of leaving CodeDeploy
waiting for the hook timeout.
"""

from __future__ import annotations

import json
import math
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Callable, Protocol

USER_AGENT = "bluegreen-lifecycle-hook/1.0"
SAFETY_MARGIN_MS = 5000


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    elapsed_seconds: float


class HttpClient(Protocol):
    def get(self, url: str, timeout: float) -> HttpResponse: ...


class UrllibClient:
    """Real client: HTTPS with certificate verification, no redirects followed."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
            return None

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context()), self._NoRedirect()
        )

    def get(self, url: str, timeout: float) -> HttpResponse:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
        start = self._clock()
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read(65536)
                status = response.status
        except urllib.error.HTTPError as exc:  # 4xx/5xx/3xx still carry a status
            with exc:
                body = exc.read(65536) if exc.fp else b""
            status = exc.code
        return HttpResponse(status, body, self._clock() - start)


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    expected_tag: str
    requests: int = 20
    p95_budget_ms: float = 500.0
    request_timeout_seconds: float = 5.0
    health_path: str = "/healthz"
    version_path: str = "/version"

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("https://", "http://")):
            raise ValueError(f"base_url must be an http(s) URL, got {self.base_url!r}")
        if not self.expected_tag:
            raise ValueError("expected_tag is required")
        if self.requests < 1:
            raise ValueError("requests must be >= 1")
        if self.p95_budget_ms <= 0 or self.request_timeout_seconds <= 0:
            raise ValueError("p95_budget_ms and request_timeout_seconds must be > 0")

    def url(self, path: str) -> str:
        return self.base_url.rstrip("/") + path


@dataclass
class SmokeResult:
    ok: bool
    base_url: str
    expected_tag: str
    passed: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    p95_ms: float | None = None
    samples: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def p95(values: list[float]) -> float:
    """Nearest-rank 95th percentile."""
    if not values:
        raise ValueError("no samples")
    ordered = sorted(values)
    rank = math.ceil(0.95 * len(ordered))
    return ordered[rank - 1]


class OutOfTime(RuntimeError):
    pass


def _reported_tag(body: bytes) -> str | None:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    tag = payload.get("image_tag") if isinstance(payload, dict) else None
    return tag if isinstance(tag, str) and tag else None


def run_smoke(
    cfg: SmokeConfig,
    client: HttpClient,
    remaining_ms: Callable[[], int] | None = None,
) -> SmokeResult:
    result = SmokeResult(ok=False, base_url=cfg.base_url, expected_tag=cfg.expected_tag)

    def fetch(path: str) -> HttpResponse:
        if remaining_ms is not None:
            needed = cfg.request_timeout_seconds * 1000 + SAFETY_MARGIN_MS
            if remaining_ms() < needed:
                raise OutOfTime("not enough Lambda time left for another request")
        return client.get(cfg.url(path), cfg.request_timeout_seconds)

    try:
        health = fetch(cfg.health_path)
        if health.status != 200:
            result.failures.append(f"health {cfg.health_path} returned {health.status}, expected 200")
            return result
        result.passed.append(f"health {cfg.health_path} 200")

        version = fetch(cfg.version_path)
        if version.status != 200:
            result.failures.append(f"version {cfg.version_path} returned {version.status}, expected 200")
        else:
            reported = _reported_tag(version.body)
            if reported is None:
                result.failures.append(f"version {cfg.version_path} did not return JSON with an image_tag")
            elif reported == cfg.expected_tag:
                result.passed.append(f"version image_tag {reported}")
            else:
                result.failures.append(f"version image_tag {reported!r} != expected {cfg.expected_tag!r}")

        latencies: list[float] = []
        errors = 0
        for _ in range(cfg.requests):
            response = fetch(cfg.health_path)
            latencies.append(response.elapsed_seconds * 1000)
            if response.status != 200:
                errors += 1
        result.samples = len(latencies)
        result.p95_ms = round(p95(latencies), 1)
        if errors:
            result.failures.append(f"{errors}/{cfg.requests} latency-sample requests were not 200")
        if result.p95_ms > cfg.p95_budget_ms:
            result.failures.append(f"p95 {result.p95_ms} ms over budget {cfg.p95_budget_ms} ms")
        else:
            result.passed.append(f"p95 {result.p95_ms} ms within {cfg.p95_budget_ms} ms over {cfg.requests} requests")
    except OutOfTime as exc:
        result.failures.append(str(exc))
        return result

    result.ok = not result.failures
    return result
