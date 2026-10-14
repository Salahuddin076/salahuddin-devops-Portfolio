#!/usr/bin/env python3
"""Policy lint for CodeBuild buildspec files (stdlib only, no PyYAML).

Rules (every buildspec):
  BS001  `version: 0.2`
  BS002  no secret-looking names (PASSWORD, SECRET, TOKEN, ...) in `env: variables`;
         secrets belong in `env: secrets-manager` or `env: parameter-store`
  BS003  every `env: secrets-manager` value uses `secret-id:json-key`
         (without the key, the variable receives the whole JSON document)
  BS004  at least one report group is declared, each with `files` and `file-format`

Rules (buildspecs that run `docker build`):
  BS005  the image tag is derived from $CODEBUILD_RESOLVED_SOURCE_VERSION
         (directly or through shell variables) and is never `latest`
  BS006  a Trivy image scan gates the build: `--exit-code 1` with CRITICAL in `--severity`
  BS007  the Trivy gate runs before the first `docker push`

The parser understands the YAML subset buildspecs use here: nested block
mappings, block sequences of scalars, quoted or plain scalars and comments.
Anything else (block scalars, flow collections, anchors) is reported as
BS000 rather than guessed at.

Usage: check_buildspec.py [FILE ...]   (defaults to ../buildspec/*.yml)
Exit code 1 if any file has a finding.
"""

from __future__ import annotations

import glob
import os
import re
import sys
from dataclasses import dataclass

SECRET_NAME_RE = re.compile(
    r"(PASSWORD|PASSWD|PWD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|CREDENTIAL|ACCESS_?KEY)", re.IGNORECASE
)
ASSIGNMENT_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
VAR_REF_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")
TAG_SOURCE = "CODEBUILD_RESOLVED_SOURCE_VERSION"


class ParseError(ValueError):
    def __init__(self, line_no: int, message: str) -> None:
        super().__init__(f"line {line_no}: {message}")
        self.line_no = line_no


@dataclass
class Finding:
    rule: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.message}"


# --------------------------------------------------------------------------- parser


def _strip_comment(text: str) -> str:
    """Remove a trailing ` # comment` that is outside quotes."""
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t"):
            return text[:i].rstrip()
    return text.rstrip()


def _scalar(raw: str, line_no: int) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    if raw[:1] in ("|", ">"):
        raise ParseError(line_no, "block scalars are not supported by this lint")
    if raw[:1] in ("[", "{", "&", "*", "!"):
        raise ParseError(line_no, f"unsupported YAML construct: {raw[:20]!r}")
    return raw


def _split_key(text: str) -> tuple[str, str] | None:
    """Split `key: value` (key unquoted or quoted). None if not a mapping entry."""
    match = re.match(r"""^("[^"]*"|'[^']*'|[^\s'"#:][^:]*?):(?:\s+(.*)|\s*)$""", text)
    if not match:
        return None
    key = match.group(1)
    if key[0] in ("'", '"'):
        key = key[1:-1]
    return key, match.group(2) or ""


def parse_yaml_subset(text: str):
    """Parse the buildspec subset into dicts, lists of strings and strings."""
    lines = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ParseError(line_no, "tabs are not allowed for indentation")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((line_no, indent, raw.strip()))

    pos = 0

    def parse_block(indent: int):
        nonlocal pos
        if pos >= len(lines):
            return {}
        if lines[pos][2].startswith("- ") or lines[pos][2] == "-":
            return parse_sequence(indent)
        return parse_mapping(indent)

    def parse_sequence(indent: int) -> list:
        nonlocal pos
        items = []
        while pos < len(lines):
            line_no, ind, content = lines[pos]
            if ind < indent:
                break
            if ind > indent:
                raise ParseError(line_no, "unexpected indentation in sequence")
            if not (content.startswith("- ") or content == "-"):
                break
            item = content[1:].strip()
            if not item:
                raise ParseError(line_no, "nested collections in sequences are not supported")
            # Sequence items are always scalars here (shell commands contain colons).
            if item in ("|", ">") or item[:2] in ("|-", "|+", ">-", ">+"):
                raise ParseError(line_no, "block scalars are not supported by this lint")
            items.append(_scalar(item, line_no) if item[:1] in ("'", '"') else item)
            pos += 1
        return items

    def parse_mapping(indent: int) -> dict:
        nonlocal pos
        result: dict = {}
        while pos < len(lines):
            line_no, ind, content = lines[pos]
            if ind < indent:
                break
            if ind > indent:
                raise ParseError(line_no, "unexpected indentation")
            if content.startswith("- "):
                break
            content = _strip_comment(content)
            split = _split_key(content)
            if split is None:
                raise ParseError(line_no, f"expected 'key: value', got {content[:40]!r}")
            key, value = split
            if key in result:
                raise ParseError(line_no, f"duplicate key {key!r}")
            pos += 1
            if value:
                result[key] = _scalar(value, line_no)
            elif pos < len(lines) and (
                lines[pos][1] > ind or (lines[pos][1] == ind and lines[pos][2].startswith("- "))
            ):
                result[key] = parse_block(lines[pos][1])
            else:
                result[key] = None
        return result

    doc = parse_mapping(lines[0][1] if lines else 0)
    if pos != len(lines):
        raise ParseError(lines[pos][0], "could not parse the rest of the document")
    return doc


# --------------------------------------------------------------------------- rules


def _commands(doc: dict) -> list[str]:
    """All phase commands in execution order."""
    phases = doc.get("phases") or {}
    ordered = []
    for phase in ("install", "pre_build", "build", "post_build"):
        body = phases.get(phase) or {}
        if isinstance(body, dict):
            for key in ("commands", "finally"):
                cmds = body.get(key) or []
                if isinstance(cmds, list):
                    ordered.extend(str(c) for c in cmds)
    return ordered


def _assignments(commands: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for command in commands:
        match = ASSIGNMENT_RE.match(command)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def _derives_from(expr: str, target: str, assignments: dict[str, str], depth: int = 0) -> bool:
    if target in expr:
        return True
    if depth > 8:
        return False
    return any(
        name in assignments and _derives_from(assignments[name], target, assignments, depth + 1)
        for name in VAR_REF_RE.findall(expr)
    )


def _image_tag_expr(ref: str) -> str:
    """The tag part of an image reference such as "$REPO:$IMAGE_TAG"."""
    ref = ref.strip().strip("'\"")
    last = ref.rsplit("/", 1)[-1]
    if "@" in last:
        return ""
    return last.rsplit(":", 1)[1] if ":" in last else ""


def _docker_build_tags(command: str) -> list[str]:
    tokens = command.split()
    tags = []
    for i, token in enumerate(tokens):
        if token in ("-t", "--tag") and i + 1 < len(tokens):
            tags.append(tokens[i + 1])
        elif token.startswith("--tag="):
            tags.append(token.split("=", 1)[1])
    return tags


def _secret_ref_has_json_key(ref: str) -> bool:
    ref = ref.strip()
    if ref.startswith("arn:"):
        # arn:aws:secretsmanager:<region>:<account>:secret:<name>[:json-key[:stage[:version]]]
        parts = ref.split(":")
        return len(parts) >= 8 and bool(parts[7])
    secret_id, sep, key = ref.partition(":")
    return bool(secret_id) and bool(sep) and bool(key.split(":", 1)[0])


def check_doc(doc: dict) -> list[Finding]:
    findings: list[Finding] = []

    if str(doc.get("version")) != "0.2":
        findings.append(Finding("BS001", f"version must be 0.2, got {doc.get('version')!r}"))

    env = doc.get("env") or {}
    variables = env.get("variables") or {}
    if isinstance(variables, dict):
        for name in variables:
            if SECRET_NAME_RE.search(name):
                findings.append(
                    Finding(
                        "BS002",
                        f"env.variables.{name} looks like a secret in plaintext; "
                        "use env.secrets-manager with secret-id:json-key",
                    )
                )

    secrets = env.get("secrets-manager") or {}
    if isinstance(secrets, dict):
        for name, ref in secrets.items():
            if not _secret_ref_has_json_key(str(ref or "")):
                findings.append(
                    Finding(
                        "BS003",
                        f"env.secrets-manager.{name} = {ref!r} has no :json-key; "
                        "the variable would receive the whole JSON secret",
                    )
                )

    reports = doc.get("reports")
    if not isinstance(reports, dict) or not reports:
        findings.append(Finding("BS004", "no reports declared (test or scan results must reach a report group)"))
    else:
        for group, body in reports.items():
            if not isinstance(body, dict) or not body.get("files") or not body.get("file-format"):
                findings.append(Finding("BS004", f"report group {group!r} needs both files and file-format"))

    commands = _commands(doc)
    build_cmds = [(i, c) for i, c in enumerate(commands) if re.search(r"\bdocker\s+build\b", c)]
    if not build_cmds:
        return findings

    assignments = _assignments(commands)
    variables_map = {k: str(v) for k, v in variables.items()} if isinstance(variables, dict) else {}
    lookup = {**variables_map, **assignments}

    tags_checked = 0
    for _, command in build_cmds:
        for ref in _docker_build_tags(command):
            tags_checked += 1
            tag = _image_tag_expr(ref)
            if tag.lower() == "latest":
                findings.append(Finding("BS005", f"image tag 'latest' is mutable: {ref}"))
            elif not tag or not _derives_from(tag, TAG_SOURCE, lookup):
                findings.append(Finding("BS005", f"image tag in {ref!r} is not derived from ${TAG_SOURCE}"))
    if tags_checked == 0:
        findings.append(Finding("BS005", f"docker build has no -t tag derived from ${TAG_SOURCE}"))

    for command in commands:
        if re.search(r"\bdocker\s+(push|tag)\b", command) and re.search(r":latest\b", command):
            findings.append(Finding("BS005", f"pushes or tags 'latest': {command}"))

    gate_index = None
    for i, command in enumerate(commands):
        if re.search(r"\btrivy\b.*\bimage\b", command):
            severity = re.search(r"--severity[ =](\S+)", command)
            if re.search(r"--exit-code[ =]1\b", command) and severity and "CRITICAL" in severity.group(1):
                gate_index = i
                break
    if gate_index is None:
        findings.append(
            Finding("BS006", "no Trivy image scan with --exit-code 1 and --severity including CRITICAL")
        )

    push_indexes = [i for i, c in enumerate(commands) if re.search(r"\bdocker\s+push\b", c)]
    if gate_index is not None and push_indexes and push_indexes[0] < gate_index:
        findings.append(Finding("BS007", "docker push runs before the Trivy gate; an unscanned image reaches ECR"))

    return findings


def check_file(path: str) -> list[Finding]:
    try:
        with open(path, encoding="utf-8") as handle:
            doc = parse_yaml_subset(handle.read())
    except OSError as exc:
        return [Finding("BS000", f"cannot read: {exc}")]
    except ParseError as exc:
        return [Finding("BS000", f"cannot parse: {exc}")]
    if not isinstance(doc, dict):
        return [Finding("BS000", "top level must be a mapping")]
    return check_doc(doc)


def default_files() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    return sorted(glob.glob(os.path.join(here, "..", "buildspec", "*.yml")))


def main(argv: list[str] | None = None) -> int:
    files = list(sys.argv[1:] if argv is None else argv) or default_files()
    if not files:
        print("no buildspec files found", file=sys.stderr)
        return 1
    failed = 0
    for path in files:
        findings = check_file(path)
        display = os.path.relpath(path)
        if findings:
            failed += 1
            print(f"FAIL {display}")
            for finding in findings:
                print(f"  {finding}")
        else:
            print(f"PASS {display}")
    print(f"{len(files) - failed}/{len(files)} buildspec file(s) passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
