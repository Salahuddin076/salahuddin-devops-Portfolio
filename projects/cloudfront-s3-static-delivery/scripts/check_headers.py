#!/usr/bin/env python3
"""Check an HTTP response for the site's security header set.

Input is either a captured header dump (``curl -sSI https://www.example.com/
> headers.txt``, or ``curl -sSIL`` for a redirect chain, in which case the
last response is checked), or, only when given explicitly with ``--url``, a
live HEAD request. The tests never use the network.

Checks (FAIL fails the run, WARN does not):

* ``Strict-Transport-Security``: present, ``max-age`` >= 31536000 (one
  year). WARN without ``includeSubDomains``.
* ``Content-Security-Policy``: present and non-empty. WARN on
  ``'unsafe-inline'`` / ``'unsafe-eval'`` in ``script-src`` (or in
  ``default-src`` when there is no ``script-src``), or no ``frame-ancestors``.
* ``X-Content-Type-Options``: exactly ``nosniff``.
* ``X-Frame-Options``: ``DENY`` or ``SAMEORIGIN``.
* ``Referrer-Policy``: one of the policies that do not leak full URLs
  cross-origin.

Exit codes: 0 all checks pass, 1 a check failed, 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

ONE_YEAR = 31_536_000

SAFE_REFERRER_POLICIES = {
    "no-referrer",
    "same-origin",
    "strict-origin",
    "strict-origin-when-cross-origin",
}

STATUS_LINE = re.compile(r"^HTTP/\d(?:\.\d)?\s+\d{3}")


class HeaderError(ValueError):
    """The input is not a parseable header dump."""


@dataclass
class Finding:
    header: str
    level: str  # PASS, WARN, FAIL
    message: str


def parse_headers(text: str) -> tuple[str | None, dict[str, list[str]]]:
    """Return (status line, lowercased name -> values) of the LAST response.

    Accepts curl -I output (one or more responses, each starting with a
    status line) or bare ``Name: value`` lines.
    """
    blocks: list[tuple[str | None, list[str]]] = []
    current: tuple[str | None, list[str]] | None = None
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if STATUS_LINE.match(line):
            current = (line.strip(), [])
            blocks.append(current)
        elif line.strip():
            if current is None:
                current = (None, [])
                blocks.append(current)
            current[1].append(line)
    if not blocks:
        raise HeaderError("no headers found")

    status, lines = blocks[-1]
    headers: dict[str, list[str]] = {}
    for line in lines:
        if line[0] in " \t" or ":" not in line:
            raise HeaderError(f"not a header line: {line!r}")
        name, _, value = line.partition(":")
        headers.setdefault(name.strip().lower(), []).append(value.strip())
    if not headers:
        raise HeaderError("the last response has no headers")
    return status, headers


def csp_directives(value: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for part in value.split(";"):
        tokens = part.split()
        if tokens:
            out.setdefault(tokens[0].lower(), tokens[1:])
    return out


def check_hsts(values: list[str] | None) -> list[Finding]:
    name = "Strict-Transport-Security"
    if not values:
        return [Finding(name, "FAIL", "missing")]
    value = values[0]
    match = re.search(r"(?i)(?:^|;)\s*max-age\s*=\s*\"?(\d+)\"?", value)
    if not match:
        return [Finding(name, "FAIL", f"no max-age in {value!r}")]
    max_age = int(match.group(1))
    if max_age < ONE_YEAR:
        return [Finding(name, "FAIL", f"max-age={max_age} is below one year ({ONE_YEAR})")]
    findings = [Finding(name, "PASS", f"max-age={max_age}")]
    if not re.search(r"(?i)includesubdomains", value):
        findings.append(Finding(name, "WARN", "no includeSubDomains"))
    return findings


def check_csp(values: list[str] | None) -> list[Finding]:
    name = "Content-Security-Policy"
    if not values or not values[0].strip():
        return [Finding(name, "FAIL", "missing")]
    directives = csp_directives(values[0])
    findings = [Finding(name, "PASS", f"{len(directives)} directives")]
    script = directives.get("script-src", directives.get("default-src", []))
    risky = [t for t in script if t.lower() in ("'unsafe-inline'", "'unsafe-eval'")]
    if risky:
        findings.append(Finding(name, "WARN", f"script sources allow {' '.join(risky)}"))
    if "frame-ancestors" not in directives:
        findings.append(Finding(name, "WARN", "no frame-ancestors (X-Frame-Options is the only clickjacking control)"))
    return findings


def check_exact(name: str, values: list[str] | None, allowed: set[str]) -> list[Finding]:
    if not values:
        return [Finding(name, "FAIL", "missing")]
    value = values[0].strip()
    if value.lower() not in allowed:
        return [Finding(name, "FAIL", f"{value!r} is not one of {', '.join(sorted(allowed))}")]
    return [Finding(name, "PASS", value)]


def check(headers: dict[str, list[str]]) -> list[Finding]:
    findings: list[Finding] = []
    findings += check_hsts(headers.get("strict-transport-security"))
    findings += check_csp(headers.get("content-security-policy"))
    findings += check_exact("X-Content-Type-Options", headers.get("x-content-type-options"), {"nosniff"})
    findings += check_exact("X-Frame-Options", headers.get("x-frame-options"), {"deny", "sameorigin"})
    findings += check_exact("Referrer-Policy", headers.get("referrer-policy"), SAFE_REFERRER_POLICIES)
    return findings


def fetch(url: str, timeout: float) -> str:
    """HEAD request; returns a curl-style dump. Only used with --url."""
    if not url.startswith("https://"):
        raise HeaderError("--url must be an https:// URL")
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "check_headers.py"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (https enforced above)
        lines = [f"HTTP/1.1 {response.status} {response.reason}"]
        lines += [f"{k}: {v}" for k, v in response.headers.items()]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify security response headers from a captured dump or a URL.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("headers_file", nargs="?", type=Path, help="captured headers, e.g. from curl -sSI")
    source.add_argument("--url", help="fetch live headers with a HEAD request (explicit opt-in to network access)")
    parser.add_argument("--timeout", type=float, default=10.0, help="--url timeout in seconds")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    try:
        if args.url:
            label = args.url
            text = fetch(args.url, args.timeout)
        else:
            label = str(args.headers_file)
            try:
                text = args.headers_file.read_text(encoding="utf-8")
            except (FileNotFoundError, IsADirectoryError, UnicodeDecodeError) as exc:
                raise HeaderError(f"cannot read {args.headers_file}: {exc}") from None
        status, headers = parse_headers(text)
    except (HeaderError, OSError) as exc:
        print(f"check_headers: {exc}", file=sys.stderr)
        return 2

    findings = check(headers)
    failed = any(f.level == "FAIL" for f in findings)

    if args.json:
        print(json.dumps({
            "source": label,
            "status": status,
            "result": "FAIL" if failed else "PASS",
            "findings": [asdict(f) for f in findings],
        }, indent=2))
    else:
        print(f"check_headers: {label}" + (f" ({status})" if status else ""))
        for f in findings:
            print(f"{f.level:<4}  {f.header:<26} {f.message}")
        fails = sum(f.level == "FAIL" for f in findings)
        warns = sum(f.level == "WARN" for f in findings)
        print(f"Result: {'FAIL' if failed else 'PASS'} ({fails} fail, {warns} warn)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
