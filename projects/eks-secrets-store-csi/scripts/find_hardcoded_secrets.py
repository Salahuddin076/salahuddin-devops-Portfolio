#!/usr/bin/env python3
"""Find hard-coded credentials in a source tree (stdlib, read-only).

Usage:
  find_hardcoded_secrets.py [ROOT] [--allowlist FILE] [--format text|json]

Rules:
  HS001  AWS access key ID (AKIA / ASIA / ABIA / ACCA + 16 chars)
  HS002  AWS secret access key assigned to an aws_secret_access_key-style name
  HS003  private key header (-----BEGIN ... PRIVATE KEY-----)
  HS004  a secret-looking name assigned a quoted literal (password = "...", API_KEY: '...')
  HS005  a quoted high-entropy string (random-looking token >= 20 chars)

Findings print the file, line, rule and a *masked* value (first 4 characters
and the length). The detector never prints a full match.

Allowlist (default: .secrets-allowlist in ROOT). One entry per line, each
with a mandatory `# reason`:
  path:<glob>     skip files matching the glob (relative to ROOT, ** allowed)
  regex:<pattern> skip a finding whose line matches the pattern
An entry without a reason is a usage error: an allowlist nobody can explain
is how real keys get waved through.

Exit status: 0 clean, 1 findings, 2 usage error.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secret_patterns import AWS_ACCESS_KEY_ID, PRIVATE_KEY_HEADER, is_high_entropy, is_secret_name, mask  # noqa: E402

SKIP_DIRS = {".git", ".terraform", "__pycache__", "node_modules", ".venv", "venv", "charts"}
MAX_BYTES = 1_000_000

AWS_SECRET_ASSIGN = re.compile(
    r"(?i)aws_?secret_?access_?key\s*[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])")
# name = "value" / name: 'value' / "name": "value"
ASSIGNMENT = re.compile(
    r"""(?P<name>[A-Za-z_][A-Za-z0-9_.\-]*)["']?\s*(?::|=|:=|=>)\s*(?P<q>["'])(?P<value>[^"'\n]*)(?P=q)""")
QUOTED = re.compile(r"""(["'])([A-Za-z0-9+/=_\-]{20,})\1""")
# Values that are references or placeholders, not credentials.
PLACEHOLDER = re.compile(
    r"""(?ix)^(
        \$\{?[A-Za-z_][A-Za-z0-9_]*\}?          # $VAR / ${VAR}
      | \{\{.*\}\}                              # templating
      | \{[A-Za-z_][\w.]*\}                     # an f-string / format field
      | <[^>]+>                                 # <your-password>
      | \*+ | x+ | changeme-placeholder
      | (?:example|placeholder|redacted|dummy|test|fake)[\w\-]*
      | /[\w\-./]*                              # a path (the _FILE convention)
      | arn:aws[\w\-]*:.*                       # an ARN names a secret, it isn't one
    )$""")
MIN_VALUE_LEN = 6


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    detail: str

    def text(self) -> str:
        return f"{self.path}:{self.line}: {self.rule} {self.detail}"


@dataclass
class Allowlist:
    globs: list[str]
    patterns: list[re.Pattern]

    @classmethod
    def load(cls, path: Path | None) -> "Allowlist":
        globs, patterns = [], []
        if path is None or not path.exists():
            return cls(globs, patterns)
        for n, raw in enumerate(path.read_text().splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            entry, sep, reason = line.partition(" #")
            if not sep or not reason.strip():
                raise ValueError(f"{path}:{n}: allowlist entry has no `# reason`")
            kind, _, value = entry.strip().partition(":")
            if kind == "path" and value:
                globs.append(value)
            elif kind == "regex" and value:
                patterns.append(re.compile(value))
            else:
                raise ValueError(f"{path}:{n}: expected `path:<glob>` or `regex:<pattern>`")
        return cls(globs, patterns)

    def skips_path(self, rel: str) -> bool:
        return any(fnmatch.fnmatch(rel, g) for g in self.globs)

    def skips_line(self, line: str) -> bool:
        return any(p.search(line) for p in self.patterns)


def scan_line(line: str) -> list[tuple[str, str]]:
    """Return (rule, masked detail) for one line. Order matters: specific rules first."""
    hits: list[tuple[str, str]] = []
    spans: list[tuple[int, int]] = []

    def claimed(span):
        return any(a <= span[0] < b or span[0] <= a < span[1] for a, b in spans)

    for m in AWS_ACCESS_KEY_ID.finditer(line):
        hits.append(("HS001", f"AWS access key ID {mask(m.group(0))}"))
        spans.append(m.span())
    for m in AWS_SECRET_ASSIGN.finditer(line):
        hits.append(("HS002", f"AWS secret access key {mask(m.group(1))}"))
        spans.append(m.span())
    if PRIVATE_KEY_HEADER.search(line):
        hits.append(("HS003", "private key header"))
        return hits
    for m in ASSIGNMENT.finditer(line):
        value = m.group("value")
        if claimed(m.span("value")):
            continue
        if is_secret_name(m.group("name")) and len(value) >= MIN_VALUE_LEN and not PLACEHOLDER.match(value):
            hits.append(("HS004", f"`{m.group('name')}` assigned a literal {mask(value)}"))
            spans.append(m.span("value"))
    for m in QUOTED.finditer(line):
        if claimed(m.span(2)):
            continue
        if is_high_entropy(m.group(2)):
            hits.append(("HS005", f"high-entropy string {mask(m.group(2))}"))
            spans.append(m.span(2))
    return hits


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def scan_tree(root: Path, allowlist: Allowlist) -> tuple[list[Finding], int]:
    findings, scanned = [], 0
    for path in iter_files(root):
        rel = path.relative_to(root).as_posix()
        if allowlist.skips_path(rel):
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue  # binary
        scanned += 1
        for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            if allowlist.skips_line(line):
                continue
            for rule, detail in scan_line(line):
                findings.append(Finding(rel, n, rule, detail))
    return findings, scanned


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("root", nargs="?", default=".")
    p.add_argument("--allowlist", help="allowlist file (default: ROOT/.secrets-allowlist)")
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"find_hardcoded_secrets: not a directory: {root}", file=sys.stderr)
        return 2
    try:
        allowlist = Allowlist.load(Path(args.allowlist) if args.allowlist else root / ".secrets-allowlist")
    except (OSError, ValueError, re.error) as exc:
        print(f"find_hardcoded_secrets: {exc}", file=sys.stderr)
        return 2
    findings, scanned = scan_tree(root, allowlist)
    if args.format == "json":
        print(json.dumps({"files_scanned": scanned, "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        for f in findings:
            print(f.text())
        print(f"find_hardcoded_secrets: {scanned} files scanned, {len(findings)} finding(s)"
              f" ({len(allowlist.globs)} path and {len(allowlist.patterns)} line allowlist entries)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
