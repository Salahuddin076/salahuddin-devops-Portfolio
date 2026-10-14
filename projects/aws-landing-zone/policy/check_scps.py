#!/usr/bin/env python3
"""Static checks for the landing zone's service control policies (SCPs).

Reads every ``*.json`` and ``*.json.tftpl`` file in the SCP directory
(default: ``terraform/modules/guardrails/policies/scp``) and the attachment
map (default: ``policy/attachments.json``), then applies the rules in
``RULES``. Templates are rendered first with the values in
``policy/template-values.json``; only ``${jsonencode(name)}`` placeholders are
supported, which is all the shipped templates use.

Size is measured on the minified document (``json.dumps`` with compact
separators). That is what the guardrails module submits, because it wraps
every policy in ``jsonencode(jsondecode(...))``.

Exit codes: 0 no findings, 1 at least one finding, 2 bad input (missing
directory, unreadable attachment map, bad flags).

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parent.parent
DEFAULT_SCP_DIR = PROJECT / "terraform" / "modules" / "guardrails" / "policies" / "scp"
DEFAULT_ATTACHMENTS = PROJECT / "policy" / "attachments.json"
DEFAULT_TEMPLATE_VALUES = PROJECT / "policy" / "template-values.json"

MAX_SCP_CHARS = 5120          # AWS Organizations quota for an SCP document
MAX_SCPS_PER_TARGET = 5       # directly attached SCPs per root, OU or account
POLICY_VERSION = "2012-10-17"
AWS_MANAGED = {"FullAWSAccess"}

# Requests the region deny must never block. Each sample action has to be
# matched by a NotAction pattern of every region-deny statement. These are
# global services (IAM, Organizations, CloudFront, Route 53, Support) or
# services served from a single region (STS global endpoint, Budgets, Health).
REQUIRED_GLOBAL_ACTIONS = (
    "iam:CreateRole",
    "organizations:DescribeOrganization",
    "cloudfront:CreateDistribution",
    "route53:ChangeResourceRecordSets",
    "support:CreateCase",
    "sts:AssumeRole",
    "budgets:ViewBudget",
    "health:DescribeEvents",
)

PLACEHOLDER = re.compile(r"\$\{jsonencode\(([A-Za-z_][A-Za-z0-9_]*)\)\}")


class InputError(Exception):
    """Unusable input: exit code 2."""


@dataclass(frozen=True)
class Rule:
    id: str
    title: str


@dataclass
class Finding:
    rule_id: str
    subject: str
    message: str


@dataclass
class Policy:
    name: str            # file name without .json / .json.tftpl
    path: Path
    document: dict | None
    minified_size: int


RULES: dict[str, Rule] = {
    r.id: r
    for r in (
        Rule("SCP-001", "Policy file is valid JSON (after template rendering) with a Statement list"),
        Rule("SCP-002", f"Minified policy is at most {MAX_SCP_CHARS:,} characters"),
        Rule("SCP-003", f'Version is "{POLICY_VERSION}"'),
        Rule("SCP-004", "Every statement has a unique Sid"),
        Rule("SCP-005", 'No Allow statement with a wildcard ("*") action'),
        Rule("SCP-006", "Region-deny statements use NotAction and exempt the required global services"),
        Rule("SCP-007", f"At most {MAX_SCPS_PER_TARGET} SCPs attached to any one target (FullAWSAccess counts)"),
        Rule("SCP-008", "Every attached SCP exists"),
    )
}


# ----------------------------------------------------------------------------- loading


def policy_name(path: Path) -> str:
    name = path.name
    for suffix in (".json.tftpl", ".json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def render_template(text: str, values: dict[str, Any]) -> str:
    """Render ``${jsonencode(name)}`` placeholders the way templatefile() would."""

    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            raise ValueError(f"template variable '{key}' has no value")
        return json.dumps(values[key])

    rendered = PLACEHOLDER.sub(repl, text)
    if "${" in rendered or "%{" in rendered:
        raise ValueError("unsupported template expression (only ${jsonencode(name)} is supported)")
    return rendered


def load_json_file(path: Path, what: str) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"cannot read {what} {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError(f"{what} {path} must be a JSON object")
    return data


def load_template_values(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    data = load_json_file(path, "template values")
    return {k: v for k, v in data.items() if k != "description"}


def minify(document: Any) -> str:
    return json.dumps(document, separators=(",", ":"))


def load_policies(scp_dir: Path, template_values: dict[str, Any]) -> tuple[list[Policy], list[Finding]]:
    """Load every policy file. Unparseable files become SCP-001 findings."""
    if not scp_dir.is_dir():
        raise InputError(f"SCP directory not found: {scp_dir}")
    files = sorted(list(scp_dir.glob("*.json")) + list(scp_dir.glob("*.json.tftpl")))
    files = [f for f in files if f.name != "attachments.json"]
    policies: list[Policy] = []
    findings: list[Finding] = []
    for path in files:
        name = policy_name(path)
        try:
            text = path.read_text()
            if path.name.endswith(".tftpl"):
                text = render_template(text, template_values)
            document = json.loads(text)
        except (ValueError, OSError) as exc:
            findings.append(Finding("SCP-001", path.name, f"not valid JSON: {exc}"))
            policies.append(Policy(name, path, None, 0))
            continue
        if not isinstance(document, dict) or not isinstance(document.get("Statement"), (list, dict)):
            findings.append(Finding("SCP-001", path.name, "document has no Statement"))
            policies.append(Policy(name, path, None, 0))
            continue
        policies.append(Policy(name, path, document, len(minify(document))))
    return policies, findings


def load_attachments(path: Path) -> dict:
    data = load_json_file(path, "attachment map")
    attachments = data.get("attachments")
    if not isinstance(attachments, dict) or not all(
        isinstance(v, list) and all(isinstance(p, str) for p in v) for v in attachments.values()
    ):
        raise InputError(f"{path}: 'attachments' must map a target key to a list of policy names")
    hierarchy = data.get("hierarchy", {})
    if not isinstance(hierarchy, dict):
        raise InputError(f"{path}: 'hierarchy' must map a target key to its parent key (or null)")
    return {"attachments": attachments, "hierarchy": hierarchy}


# ----------------------------------------------------------------------------- matching helpers


def as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def statements(document: dict) -> list[dict]:
    return [s for s in as_list(document.get("Statement")) if isinstance(s, dict)]


def wildcard_to_regex(pattern: str) -> re.Pattern:
    """IAM wildcard: ``*`` any run of characters, ``?`` exactly one."""
    parts = [".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in pattern]
    return re.compile("".join(parts), re.IGNORECASE | re.DOTALL)


def action_matches(pattern: str, action: str) -> bool:
    return wildcard_to_regex(pattern).fullmatch(action) is not None


def is_region_deny(stmt: dict) -> bool:
    if stmt.get("Effect") != "Deny":
        return False
    for operator_block in (stmt.get("Condition") or {}).values():
        if isinstance(operator_block, dict) and any(k.lower() == "aws:requestedregion" for k in operator_block):
            return True
    return False


# ----------------------------------------------------------------------------- rules


def check_policy(policy: Policy) -> list[Finding]:
    doc = policy.document
    if doc is None:
        return []
    out: list[Finding] = []
    subject = policy.path.name

    if policy.minified_size > MAX_SCP_CHARS:
        out.append(Finding("SCP-002", subject,
                           f"minified size {policy.minified_size:,} > {MAX_SCP_CHARS:,} characters"))

    if doc.get("Version") != POLICY_VERSION:
        out.append(Finding("SCP-003", subject, f"Version is {doc.get('Version')!r}, expected {POLICY_VERSION!r}"))

    seen: set[str] = set()
    for i, stmt in enumerate(statements(doc)):
        sid = stmt.get("Sid")
        label = sid or f"Statement[{i}]"
        if not sid:
            out.append(Finding("SCP-004", subject, f"Statement[{i}] has no Sid"))
        elif sid in seen:
            out.append(Finding("SCP-004", subject, f"duplicate Sid {sid!r}"))
        else:
            seen.add(sid)

        if stmt.get("Effect") == "Allow":
            wild = [a for a in as_list(stmt.get("Action")) if "*" in str(a)]
            if wild:
                out.append(Finding("SCP-005", subject, f"{label} allows wildcard action(s) {wild}"))
            if "NotAction" in stmt:
                out.append(Finding("SCP-005", subject, f"{label} is Allow with NotAction (allows everything else)"))

        if is_region_deny(stmt):
            if "NotAction" not in stmt:
                out.append(Finding("SCP-006", subject,
                                   f"{label} denies by region with Action instead of NotAction, so global services break"))
            else:
                patterns = as_list(stmt.get("NotAction"))
                missing = [a for a in REQUIRED_GLOBAL_ACTIONS
                           if not any(action_matches(p, a) for p in patterns)]
                if missing:
                    out.append(Finding("SCP-006", subject,
                                       f"{label} does not exempt global service action(s): {', '.join(missing)}"))
    return out


def check_attachments(attachment_map: dict, known: set[str], source: str) -> list[Finding]:
    out: list[Finding] = []
    for target, names in attachment_map["attachments"].items():
        if len(names) > MAX_SCPS_PER_TARGET:
            out.append(Finding("SCP-007", f"{source}:{target}",
                               f"{len(names)} SCPs attached (limit {MAX_SCPS_PER_TARGET}, FullAWSAccess counts): {names}"))
        if len(set(names)) != len(names):
            out.append(Finding("SCP-007", f"{source}:{target}", f"duplicate attachment in {names}"))
        for name in names:
            if name not in known and name not in AWS_MANAGED:
                out.append(Finding("SCP-008", f"{source}:{target}", f"attached SCP {name!r} has no policy file"))
    return out


@dataclass
class Report:
    scp_dir: Path
    attachments_path: Path | None
    policies: list[Policy]
    attachment_map: dict | None
    findings: list[Finding]

    @property
    def failed(self) -> bool:
        return bool(self.findings)


def run(scp_dir: Path, attachments_path: Path | None, template_values_path: Path | None) -> Report:
    values = load_template_values(template_values_path)
    policies, findings = load_policies(scp_dir, values)
    for policy in policies:
        findings.extend(check_policy(policy))
    attachment_map = None
    if attachments_path is not None:
        attachment_map = load_attachments(attachments_path)
        findings.extend(check_attachments(attachment_map, {p.name for p in policies}, attachments_path.name))
    return Report(scp_dir, attachments_path, policies, attachment_map, findings)


# ----------------------------------------------------------------------------- output


def display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def format_text(report: Report) -> str:
    lines = [f"check_scps: {len(report.policies)} policies in {display(report.scp_dir)}"
             + (f", attachments from {display(report.attachments_path)}" if report.attachments_path else "")]
    failed_subjects = {f.subject for f in report.findings}
    for p in report.policies:
        status = "FAIL" if p.path.name in failed_subjects else "ok  "
        if p.document is None:
            lines.append(f"{status} {p.name:<32} unparseable")
        else:
            lines.append(f"{status} {p.name:<32} {p.minified_size:>5,} / {MAX_SCP_CHARS:,} chars"
                         f"  {len(statements(p.document))} statement(s)")
    if report.attachment_map:
        counts = ", ".join(f"{t} {len(n)}/{MAX_SCPS_PER_TARGET}" for t, n in report.attachment_map["attachments"].items())
        lines.append(f"Attachments per target: {counts}")
    for f in report.findings:
        lines.append(f"FAIL {f.rule_id}  {f.subject}: {f.message}")
    lines.append(f"Summary: {len(report.findings)} finding(s). Result: {'FAIL' if report.failed else 'PASS'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Static checks for SCP JSON files and their attachment map.")
    parser.add_argument("--scp-dir", type=Path, default=DEFAULT_SCP_DIR, help="directory of *.json / *.json.tftpl SCPs")
    parser.add_argument("--attachments", type=Path, default=DEFAULT_ATTACHMENTS, help="attachment map JSON")
    parser.add_argument("--no-attachments", action="store_true", help="skip the per-target attachment checks")
    parser.add_argument("--template-values", type=Path, default=DEFAULT_TEMPLATE_VALUES,
                        help="values for ${jsonencode(name)} placeholders")
    parser.add_argument("--list-rules", action="store_true", help="print the rule catalogue and exit")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2

    if args.list_rules:
        for rule in RULES.values():
            print(f"{rule.id}  {rule.title}")
        return 0
    try:
        report = run(args.scp_dir, None if args.no_attachments else args.attachments, args.template_values)
    except InputError as exc:
        print(f"check_scps: error: {exc}", file=sys.stderr)
        return 2
    print(format_text(report))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
