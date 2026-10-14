#!/usr/bin/env python3
"""Plan a static-site deploy: what to upload, delete and invalidate.

Given a local build directory and a JSON manifest of the objects currently in
the bucket, compute (without touching AWS):

* **upload**: new and changed files, each with its ``Cache-Control`` and
  ``Content-Type``, ordered so a viewer never gets HTML that points at an
  asset not uploaded yet (hashed assets first, then other files, HTML last);
* **delete**: remote keys that are no longer in the build (run after the
  uploads). With ``--keep-old-hashed``, superseded hashed assets are listed
  under ``retained`` instead, so a page loaded before the deploy can still
  fetch its bundle; prune them on a later deploy;
* **invalidation**: the smallest set of CloudFront paths that makes viewers
  see the change. Hashed assets are never invalidated (a new hash is a new
  URL). Changed or deleted non-hashed objects are, with ``/dir/`` added next
  to ``/dir/index.html``. Above ``--threshold`` paths, the list collapses to
  a single ``/*``.

Cache-Control policy:

* ``name.<8+ hex>.js|css``  ``public, max-age=31536000, immutable``
* ``*.html``                ``no-cache`` (always revalidate)
* anything else             ``public, max-age=300`` (``--short-ttl``)

Manifest formats accepted (``--manifest``):

* ``{"key": "etag-or-md5", ...}``
* ``{"key": {"etag": "..."}, ...}``
* the raw output of ``aws s3api list-objects-v2 --output json``
  (``{"Contents": [{"Key": ..., "ETag": ...}]}``; an empty bucket has no
  ``Contents``).

A single-part upload of an SSE-S3 object has ``ETag == MD5``. A multipart
upload's ETag (``"...-N"``) or an SSE-KMS object's ETag is not an MD5, so the
file is reported as changed: correct, just not minimal.

Exit codes: 0 success, 2 bad input. Output is JSON on stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

HASHED_ASSET = re.compile(r"\.[0-9a-f]{8,}\.(?:js|css)$")
MD5_HEX = re.compile(r"^[0-9a-f]{32}$")

CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
CACHE_HTML = "no-cache"
DEFAULT_SHORT_TTL = 300
DEFAULT_THRESHOLD = 15

# Upload phases: lower first.
PHASE_HASHED, PHASE_OTHER, PHASE_HTML = 0, 1, 2

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/svg+xml", ".svg")


class PlanError(ValueError):
    """Bad input: unreadable build directory or manifest."""


def is_hashed_asset(key: str) -> bool:
    return bool(HASHED_ASSET.search(key.rsplit("/", 1)[-1]))


def is_html(key: str) -> bool:
    return key.lower().endswith((".html", ".htm"))


def cache_control(key: str, short_ttl: int = DEFAULT_SHORT_TTL) -> str:
    if is_hashed_asset(key):
        return CACHE_IMMUTABLE
    if is_html(key):
        return CACHE_HTML
    return f"public, max-age={short_ttl}"


def content_type(key: str) -> str:
    guessed, _ = mimetypes.guess_type(key)
    if guessed is None:
        return "application/octet-stream"
    if guessed.startswith("text/") or guessed in ("application/json", "image/svg+xml", "application/manifest+json"):
        return f"{guessed}; charset=utf-8"
    return guessed


def phase(key: str) -> int:
    if is_hashed_asset(key):
        return PHASE_HASHED
    if is_html(key):
        return PHASE_HTML
    return PHASE_OTHER


def file_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_build(build_dir: Path) -> dict[str, str]:
    """Map S3 key (POSIX relative path) -> MD5 hex for every file in the build."""
    if not build_dir.is_dir():
        raise PlanError(f"build directory not found: {build_dir}")
    files: dict[str, str] = {}
    for root, dirs, names in os.walk(build_dir):
        dirs.sort()
        for name in sorted(names):
            path = Path(root) / name
            if path.is_file():
                files[path.relative_to(build_dir).as_posix()] = file_md5(path)
    return files


def normalise_etag(raw: Any) -> str:
    if not isinstance(raw, str):
        raise PlanError(f"etag must be a string, got {raw!r}")
    return raw.strip().strip('"').lower()


def load_manifest(data: Any) -> dict[str, str]:
    """Accept the three manifest shapes; return key -> normalised etag."""
    if not isinstance(data, dict):
        raise PlanError("manifest must be a JSON object")
    if "Contents" in data or "KeyCount" in data or "Prefix" in data:
        contents = data.get("Contents") or []
        if not isinstance(contents, list):
            raise PlanError("manifest Contents must be a list")
        out = {}
        for item in contents:
            if not isinstance(item, dict) or "Key" not in item or "ETag" not in item:
                raise PlanError(f"manifest Contents entries need Key and ETag: {item!r}")
            out[item["Key"]] = normalise_etag(item["ETag"])
        return out
    out = {}
    for key, value in data.items():
        if isinstance(value, dict):
            if "etag" not in value:
                raise PlanError(f"manifest entry for {key!r} has no etag")
            value = value["etag"]
        out[key] = normalise_etag(value)
    return out


def invalidation_paths_for(key: str) -> list[str]:
    """CloudFront paths for one object key; encoded, leading slash.

    ``docs/index.html`` also yields ``/docs/``: the viewer-request function
    rewrites ``/docs/`` to ``/docs/index.html`` before the cache lookup, so
    the second path is belt and braces, at the cost of one extra path.
    """
    path = "/" + quote(key, safe="/-_.~")
    paths = [path]
    if key == "index.html" or key.endswith("/index.html"):
        paths.append(path[: -len("index.html")])
    return paths


def build_plan(local: dict[str, str], remote: dict[str, str], *,
               threshold: int = DEFAULT_THRESHOLD, short_ttl: int = DEFAULT_SHORT_TTL,
               keep_old_hashed: bool = False) -> dict[str, Any]:
    if threshold < 1:
        raise PlanError("threshold must be at least 1")

    upload: list[dict[str, Any]] = []
    unchanged = 0
    for key, md5 in local.items():
        remote_etag = remote.get(key)
        if remote_etag is None:
            reason = "new"
        elif not MD5_HEX.match(remote_etag):
            reason = "changed (remote ETag is not an MD5)"
        elif remote_etag != md5:
            reason = "changed"
        else:
            unchanged += 1
            continue
        upload.append({
            "key": key,
            "reason": reason,
            "md5": md5,
            "cache_control": cache_control(key, short_ttl),
            "content_type": content_type(key),
            "phase": ("hashed-asset", "other", "html")[phase(key)],
        })
    upload.sort(key=lambda item: (phase(item["key"]), item["key"]))

    gone = sorted(set(remote) - set(local))
    # Old hashed assets can be kept for a release so that a page loaded
    # before the deploy can still fetch the bundle it references.
    retained = [k for k in gone if keep_old_hashed and is_hashed_asset(k)]
    delete = [k for k in gone if k not in retained]

    # Invalidate what a cache may hold a stale copy of: objects that existed
    # before (changed or deleted) and are not content-addressed. New keys are
    # skipped: any cached 404 for them expires after error_caching_min_ttl.
    candidates = [u["key"] for u in upload if u["reason"] != "new"] + delete
    paths: list[str] = []
    for key in sorted(candidates):
        if is_hashed_asset(key):
            continue
        for p in invalidation_paths_for(key):
            if p not in paths:
                paths.append(p)

    wildcard = len(paths) > threshold
    return {
        "upload": upload,
        "delete": delete,
        "retained": retained,
        "invalidation": {
            "paths": ["/*"] if wildcard else paths,
            "wildcard": wildcard,
            "path_count": len(paths),
            "threshold": threshold,
        },
        "summary": {
            "local_files": len(local),
            "remote_objects": len(remote),
            "new": sum(1 for u in upload if u["reason"] == "new"),
            "changed": sum(1 for u in upload if u["reason"] != "new"),
            "unchanged": unchanged,
            "deleted": len(delete),
            "retained": len(retained),
            "invalidation_paths": 1 if wildcard else len(paths),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute the upload/delete/invalidation plan for a static-site deploy.")
    parser.add_argument("build_dir", type=Path, help="local build output, e.g. site/ or dist/")
    parser.add_argument("--manifest", type=Path, required=True,
                        help="JSON of current remote objects (key -> etag, or list-objects-v2 output)")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                        help=f"collapse to /* above this many invalidation paths (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--short-ttl", type=int, default=DEFAULT_SHORT_TTL,
                        help=f"max-age for non-HTML, non-hashed files (default {DEFAULT_SHORT_TTL})")
    parser.add_argument("--keep-old-hashed", action="store_true",
                        help="do not delete hashed assets that left the build (pages loaded before the deploy may still need them)")
    parser.add_argument("--compact", action="store_true", help="single-line JSON")
    args = parser.parse_args(argv)

    try:
        try:
            manifest_data = json.loads(args.manifest.read_text(encoding="utf-8") or "{}")
        except FileNotFoundError:
            raise PlanError(f"manifest not found: {args.manifest}") from None
        except json.JSONDecodeError as exc:
            raise PlanError(f"manifest is not valid JSON: {exc}") from None
        if args.short_ttl < 0:
            raise PlanError("short-ttl must be >= 0")
        plan = build_plan(scan_build(args.build_dir), load_manifest(manifest_data),
                          threshold=args.threshold, short_ttl=args.short_ttl,
                          keep_old_hashed=args.keep_old_hashed)
    except PlanError as exc:
        print(f"deploy_plan: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(plan, indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
