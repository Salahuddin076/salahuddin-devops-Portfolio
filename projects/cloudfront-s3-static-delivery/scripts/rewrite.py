#!/usr/bin/env python3
"""Reference implementation of the CloudFront Function URI rewrite.

This module is the *specification* for
``terraform/modules/static-site/functions/uri-rewrite.js``. CloudFront
Functions run a restricted JavaScript runtime that has no local test
harness, so the behaviour is pinned here, in plain Python, with unit tests.
The JavaScript is reviewed against this file branch for branch, and
``tests/test_cloudfront_function.py`` runs both on the same events when
``node`` is installed.

``handler`` takes and returns the same shapes as the CloudFront Functions
viewer-request event (``event["request"]`` with ``uri`` and ``querystring``)
so the two implementations can be compared output for output.

Rules, in order:

1. URI ends with ``/``             -> rewrite to URI + ``index.html``
2. last segment contains ``.``     -> a file: pass through unchanged
3. otherwise                       -> 301 redirect to URI + ``/``, query
                                      string preserved

The URI is matched as CloudFront delivers it (percent-encoded). It is never
decoded, so ``%2F`` is not a slash and ``%2E`` is not a dot.

CLI: ``python3 scripts/rewrite.py /docs '/a b/?x=1'`` prints the decision
for each URI as JSON lines.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from typing import Any

REDIRECT_CACHE_CONTROL = "public, max-age=3600"


def build_query_string(querystring: dict[str, Any]) -> str:
    """Serialise a CloudFront Functions querystring object back to ``?a=1&b``.

    Mirrors ``buildQueryString`` in the JS: keys in object order, every value
    of a multi-valued key, a bare key for an empty value, values passed
    through exactly as received (still encoded).
    """
    parts: list[str] = []
    for name, entry in querystring.items():
        values = entry["multiValue"] if entry.get("multiValue") else [entry]
        for item in values:
            value = item["value"]
            parts.append(name if value == "" else f"{name}={value}")
    return "?" + "&".join(parts) if parts else ""


def handler(event: dict[str, Any]) -> dict[str, Any]:
    """Return the modified request, or a redirect response (JS-identical shape)."""
    request = copy.deepcopy(event["request"])
    uri: str = request["uri"]

    # Branch 1: directory request.
    if uri.endswith("/"):
        request["uri"] = uri + "index.html"
        return request

    # Branch 2: the last path segment looks like a file name.
    last_segment = uri[uri.rfind("/") + 1 :]
    if "." in last_segment:
        return request

    # Branch 3: extensionless path without a trailing slash.
    return {
        "statusCode": 301,
        "statusDescription": "Moved Permanently",
        "headers": {
            "location": {"value": uri + "/" + build_query_string(request.get("querystring") or {})},
            "cache-control": {"value": REDIRECT_CACHE_CONTROL},
        },
    }


def make_event(uri: str, query: str = "") -> dict[str, Any]:
    """Build a viewer-request event like CloudFront's from a URI and raw query.

    Values are kept as given (no decoding), and repeated keys become a
    ``multiValue`` list, which is how CloudFront Functions present them.
    """
    querystring: dict[str, Any] = {}
    for pair in filter(None, query.split("&")):
        name, _, value = pair.partition("=")
        if name in querystring:
            entry = querystring[name]
            entry.setdefault("multiValue", [{"value": entry["value"]}])
            entry["multiValue"].append({"value": value})
        else:
            querystring[name] = {"value": value}
    return {
        "version": "1.0",
        "context": {"eventType": "viewer-request"},
        "viewer": {"ip": "192.0.2.10"},
        "request": {"method": "GET", "uri": uri, "querystring": querystring, "headers": {}, "cookies": {}},
    }


def decide(target: str) -> dict[str, Any]:
    """Summarise the decision for a URI with an optional ``?query``."""
    uri, _, query = target.partition("?")
    result = handler(make_event(uri, query))
    if "statusCode" in result:
        return {"input": target, "action": "redirect", "status": result["statusCode"],
                "location": result["headers"]["location"]["value"]}
    if result["uri"] != uri:
        return {"input": target, "action": "rewrite", "uri": result["uri"]}
    return {"input": target, "action": "pass", "uri": uri}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show what the CloudFront URI rewrite does with each URI.")
    parser.add_argument("uris", nargs="+", help="request URIs, optionally with ?query, each starting with /")
    args = parser.parse_args(argv)
    for target in args.uris:
        if not target.startswith("/"):
            print(f"rewrite: URI must start with '/': {target!r}", file=sys.stderr)
            return 2
        print(json.dumps(decide(target)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
