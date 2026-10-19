#!/usr/bin/env python3
"""Lint a per-service ARM64 migration compatibility manifest (stdlib only).

The manifest (default: docs/compatibility-manifest.yaml) is the machine-
checkable half of docs/compatibility-checklist.md: one entry per service,
one block per platform (linux/amd64, linux/arm64), recording exactly the
things that differ across architectures and that a migration quietly breaks
if nobody checks them -- see the rule list below and
docs/compatibility-checklist.md for the reasoning behind each one.

Rules:
  GC001 error    a service is missing the linux/amd64 or linux/arm64 platform block
  GC002 error    base_image is not pinned by digest (no "@sha256:<64 hex>")
  GC003 error    image_scan.status is missing or not one of pass/fail/pending
  GC004 error    rollout.stage is canary/partial/complete but some platform's
                 image_scan.status isn't "pass" (can't promote on an unscanned
                 or failing image)
  GC005 error    image_scan.status is "pass" but critical or high findings > 0
  GC006 warning  build_method is "qemu" (native agents are the default policy;
                 see docs/decisions/0001-native-arm64-build-agents.md)
  GC007 error    build_method is "qemu" and native_modules is non-empty
                 (emulated builds hide architecture-specific native-module
                 failures instead of catching them at build time)
  GC008 warning  runtime_version differs between platforms with no
                 runtime_version_note explaining why

Exit codes: 0 nothing at or above --fail-on severity, 1 otherwise, 2 usage error.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yaml_lite  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = PROJECT / "docs" / "compatibility-manifest.yaml"

PLATFORMS = ("linux/amd64", "linux/arm64")
SCAN_STATUSES = ("pass", "fail", "pending")
PROMOTED_STAGES = ("canary", "partial", "complete")
ALL_STAGES = ("design", "native-agents", "canary", "partial", "complete")
DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
SEVERITY_ORDER = {"warning": 0, "error": 1}

RULES: dict[str, str] = {
    "GC001": "error",
    "GC002": "error",
    "GC003": "error",
    "GC004": "error",
    "GC005": "error",
    "GC006": "warning",
    "GC007": "error",
    "GC008": "warning",
}


@dataclass
class Finding:
    rule: str
    service: str
    message: str

    @property
    def severity(self) -> str:
        return RULES[self.rule]


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, rule: str, service: str, message: str) -> None:
        self.findings.append(Finding(rule, service, message))

    def at_or_above(self, threshold: str) -> list[Finding]:
        level = SEVERITY_ORDER[threshold]
        return [f for f in self.findings if SEVERITY_ORDER[f.severity] >= level]


class ManifestError(ValueError):
    pass


def _require(mapping: object, key: str, where: str) -> object:
    if not isinstance(mapping, dict) or key not in mapping:
        raise ManifestError(f"{where}: missing '{key}'")
    return mapping[key]


def check_platform(service: str, platform: str, block: object, report: Report) -> None:
    if not isinstance(block, dict):
        report.add("GC001", service, f"platform '{platform}' is not a mapping")
        return

    base_image = block.get("base_image")
    if not isinstance(base_image, str) or not DIGEST_RE.search(base_image):
        report.add("GC002", service, f"{platform}: base_image {base_image!r} is not pinned by digest (@sha256:<64 hex>)")

    scan = block.get("image_scan")
    status = scan.get("status") if isinstance(scan, dict) else None
    if status not in SCAN_STATUSES:
        report.add("GC003", service, f"{platform}: image_scan.status {status!r} must be one of {SCAN_STATUSES}")
    elif status == "pass" and isinstance(scan, dict):
        critical = scan.get("critical", 0)
        high = scan.get("high", 0)
        if (isinstance(critical, (int, float)) and critical > 0) or (isinstance(high, (int, float)) and high > 0):
            report.add("GC005", service, f"{platform}: image_scan.status is 'pass' but critical={critical} high={high}")

    build_method = block.get("build_method")
    native_modules = block.get("native_modules") or []
    if build_method == "qemu":
        report.add("GC006", service, f"{platform}: build_method is 'qemu'; native agents are the default policy")
        if isinstance(native_modules, list) and native_modules:
            report.add("GC007", service,
                       f"{platform}: build_method is 'qemu' with native_modules {native_modules}; "
                       "build these natively, emulation hides arch-specific failures")


def check_service(name: str, data: object, report: Report) -> None:
    if not isinstance(data, dict):
        report.add("GC001", name, "service entry is not a mapping")
        return

    platforms = data.get("platforms")
    if not isinstance(platforms, dict):
        report.add("GC001", name, "missing 'platforms' mapping")
        platforms = {}
    for platform in PLATFORMS:
        if platform not in platforms:
            report.add("GC001", name, f"missing platform '{platform}'")
    for platform, block in platforms.items():
        if platform in PLATFORMS:
            check_platform(name, platform, block, report)

    rollout = data.get("rollout") or {}
    stage = rollout.get("stage") if isinstance(rollout, dict) else None
    if stage in PROMOTED_STAGES:
        for platform in PLATFORMS:
            block = platforms.get(platform)
            status = block.get("image_scan", {}).get("status") if isinstance(block, dict) else None
            if status != "pass":
                report.add("GC004", name,
                           f"rollout.stage is '{stage}' but {platform} image_scan.status is {status!r}, not 'pass'")

    runtimes = {
        p: platforms[p].get("runtime_version")
        for p in PLATFORMS
        if isinstance(platforms.get(p), dict)
    }
    values = {v for v in runtimes.values() if v is not None}
    if len(values) > 1 and not data.get("runtime_version_note"):
        report.add("GC008", name,
                   f"runtime_version differs across platforms ({runtimes}) with no runtime_version_note explaining why")


def check_manifest(doc: object) -> Report:
    report = Report()
    if not isinstance(doc, dict) or "services" not in doc or not isinstance(doc["services"], dict):
        raise ManifestError("top level must be a mapping with a 'services' mapping")
    for name, data in doc["services"].items():
        check_service(name, data, report)
    return report


def load_manifest(path: Path) -> object:
    text = path.read_text(encoding="utf-8")
    docs = yaml_lite.load_all(text)
    if not docs:
        raise ManifestError("empty manifest")
    return docs[0]


def render(report: Report, path: str) -> str:
    lines = [f"{path} {f.rule} {f.severity.upper()} [{f.service}] {f.message}" for f in report.findings]
    errors = sum(f.severity == "error" for f in report.findings)
    warnings = sum(f.severity == "warning" for f in report.findings)
    if lines:
        lines.append("")
    lines.append(f"compatibility_check: {errors} error(s), {warnings} warning(s)")
    return "\n".join(lines)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("manifest", nargs="?", default=str(DEFAULT_MANIFEST), help="compatibility manifest YAML file")
    p.add_argument("--fail-on", choices=("error", "warning"), default="error",
                   help="lowest severity that makes the exit status 1 (default: error)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    path = Path(args.manifest)
    try:
        doc = load_manifest(path)
        report = check_manifest(doc)
    except (OSError, ManifestError, ValueError) as exc:
        print(f"compatibility_check: {path}: {exc}", file=sys.stderr)
        return 2
    print(render(report, str(path)))
    return 1 if report.at_or_above(args.fail_on) else 0


if __name__ == "__main__":
    sys.exit(main())
