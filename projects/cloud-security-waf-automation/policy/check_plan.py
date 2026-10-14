#!/usr/bin/env python3
"""Policy-as-code checks for a Terraform plan in JSON form.

Input is the output of ``terraform show -json tfplan``. Each rule has an ID,
a severity and remediation text. Findings can be excepted through an
exceptions file (owner, reason, expiry); expired exceptions are ignored and
reported. Output is text or SARIF 2.1.0 for GitHub code scanning.

Exit codes: 0 no unexcepted HIGH finding, 1 at least one unexcepted HIGH
finding, 2 bad input (unreadable plan, malformed exceptions file, bad flags).

Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

TOOL_NAME = "check_plan"
TOOL_VERSION = "1.0.0"
TOOL_URI = "https://github.com/Salahuddin076/salahuddin-devops-Portfolio/tree/main/projects/cloud-security-waf-automation"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

SEVERITIES = ("HIGH", "MEDIUM", "LOW")
SARIF_LEVEL = {"HIGH": "error", "MEDIUM": "warning", "LOW": "note"}
# GitHub code scanning reads properties.security-severity (0.0-10.0).
SECURITY_SEVERITY = {"HIGH": "8.0", "MEDIUM": "5.0", "LOW": "2.0"}

OPEN_CIDRS = {"0.0.0.0/0", "::/0"}
ADMIN_PORTS = (22, 3389)
IAM_POLICY_TYPES = ("aws_iam_policy", "aws_iam_role_policy", "aws_iam_user_policy", "aws_iam_group_policy")
PAB_FLAGS = ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets")


class InputError(Exception):
    """Unusable input: exit code 2."""


# ----------------------------------------------------------------------------- data model


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    severity: str
    title: str
    remediation: str


@dataclass
class Finding:
    rule_id: str
    severity: str
    address: str
    message: str
    excepted_by: dict | None = None


@dataclass
class Resource:
    address: str
    type: str
    name: str
    actions: list[str]
    after: dict
    # attribute -> addresses referenced in configuration (resolved from the
    # plan's "configuration" section; needed because ARNs and IDs of new
    # resources are unknown at plan time).
    refs: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Report:
    plan_path: str
    resources_checked: int
    findings: list[Finding]
    expired_exceptions: list[dict]
    unused_exceptions: list[dict]

    @property
    def active(self) -> list[Finding]:
        return [f for f in self.findings if f.excepted_by is None]

    @property
    def excepted(self) -> list[Finding]:
        return [f for f in self.findings if f.excepted_by is not None]

    @property
    def failed(self) -> bool:
        return any(f.severity == "HIGH" for f in self.active)


RULES: dict[str, Rule] = {
    r.id: r
    for r in (
        Rule(
            "CSP-S3-001", "S3PublicAccessBlock", "HIGH",
            "S3 bucket must have a public access block with all four flags true",
            "Add an aws_s3_bucket_public_access_block for the bucket with block_public_acls, "
            "block_public_policy, ignore_public_acls and restrict_public_buckets all set to true. "
            "Serve public content through CloudFront with origin access control instead of a public bucket.",
        ),
        Rule(
            "CSP-SG-001", "NoOpenAdminPorts", "HIGH",
            "Security group must not allow 0.0.0.0/0 or ::/0 on port 22 or 3389",
            "Remove the world-open SSH/RDP rule. Use SSM Session Manager (no inbound port), "
            "or restrict the source to a bastion security group or a known corporate range.",
        ),
        Rule(
            "CSP-IAM-001", "NoWildcardAdmin", "HIGH",
            "IAM policy must not allow Action \"*\" on Resource \"*\"",
            "Replace the wildcard statement with the specific actions and resource ARNs the workload "
            "needs. Use IAM Access Analyzer policy generation from CloudTrail activity to find them.",
        ),
        Rule(
            "CSP-RDS-001", "RdsStorageEncrypted", "HIGH",
            "RDS instance or cluster must set storage_encrypted = true",
            "Set storage_encrypted = true (and kms_key_id for a customer managed key). An existing "
            "unencrypted instance needs a snapshot, an encrypted copy and a restore; it cannot be encrypted in place.",
        ),
        Rule(
            "CSP-CT-001", "CloudTrailLogValidation", "MEDIUM",
            "CloudTrail trail must enable log file validation",
            "Set enable_log_file_validation = true so digest files prove that delivered log files "
            "were not modified or deleted.",
        ),
        Rule(
            "CSP-WAF-001", "PublicAlbHasWaf", "MEDIUM",
            "Internet-facing ALB should have a WAF web ACL association",
            "Associate a REGIONAL WAFv2 web ACL (aws_wafv2_web_acl_association) with the load balancer; "
            "terraform/modules/waf does this with associate_alb = true.",
        ),
    )
}


# ----------------------------------------------------------------------------- plan loading


def load_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InputError(f"{what} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"{what} is not valid JSON: {path}: {exc}") from exc


def _config_refs(module: dict, prefix: str, refs: dict[str, dict[str, list[str]]], var_refs: dict[str, list[str]]) -> None:
    """Collect expression references per resource address, recursing into
    modules. var_refs maps "module.x.var.y" to what the caller passed in."""
    for res in module.get("resources", []) or []:
        address = prefix + res.get("address", "")
        attrs: dict[str, list[str]] = {}
        for attr, expr in (res.get("expressions") or {}).items():
            if isinstance(expr, dict) and isinstance(expr.get("references"), list):
                attrs[attr] = [prefix + r for r in expr["references"] if isinstance(r, str)]
        refs[address] = attrs
    for call_name, call in (module.get("module_calls") or {}).items():
        call = call or {}
        child_prefix = f"{prefix}module.{call_name}."
        for var, expr in (call.get("expressions") or {}).items():
            if isinstance(expr, dict) and isinstance(expr.get("references"), list):
                var_refs[f"{child_prefix}var.{var}"] = [prefix + r for r in expr["references"] if isinstance(r, str)]
        _config_refs(call.get("module") or {}, child_prefix, refs, var_refs)


def _expand(ref_list: list[str], var_refs: dict[str, list[str]], depth: int = 0) -> list[str]:
    """Follow module input variables back to the resources they came from."""
    out: list[str] = []
    for ref in ref_list:
        out.append(ref)
        if ref in var_refs and depth < 16:
            out.extend(_expand(var_refs[ref], var_refs, depth + 1))
    return out


def load_resources(plan: Any) -> list[Resource]:
    if not isinstance(plan, dict) or not isinstance(plan.get("resource_changes"), list):
        raise InputError("plan JSON has no resource_changes list; produce it with `terraform show -json tfplan`")

    refs: dict[str, dict[str, list[str]]] = {}
    var_refs: dict[str, list[str]] = {}
    root = (plan.get("configuration") or {}).get("root_module") or {}
    _config_refs(root, "", refs, var_refs)

    resources = []
    for rc in plan["resource_changes"]:
        if not isinstance(rc, dict) or rc.get("mode", "managed") != "managed":
            continue
        change = rc.get("change") or {}
        after = change.get("after")
        if after is None:  # being destroyed: nothing to evaluate
            continue
        address = rc.get("address", "")
        # Config addresses have no instance keys: aws_lb.x[0] -> aws_lb.x
        attr_refs = refs.get(_strip_index(address), {})
        resources.append(
            Resource(
                address=address,
                type=rc.get("type", ""),
                name=rc.get("name", ""),
                actions=list(change.get("actions") or []),
                after=after if isinstance(after, dict) else {},
                refs={k: _expand(v, var_refs) for k, v in attr_refs.items()},
            )
        )
    return resources


def _strip_index(address: str) -> str:
    parts = []
    for part in address.split("."):
        parts.append(part.split("[", 1)[0])
    return ".".join(parts)


def _references(res: Resource, attr: str, target: Resource) -> bool:
    """True if res.attr refers to target (by config reference or by known value)."""
    target_cfg = _strip_index(target.address)
    for ref in res.refs.get(attr, []):
        if ref == target_cfg or ref.startswith(target_cfg + "."):
            return True
    value = res.after.get(attr)
    if value in (None, ""):
        return False
    return value in {target.after.get(k) for k in ("id", "arn", "bucket") if target.after.get(k)}


# ----------------------------------------------------------------------------- rules


def _of_type(resources: Iterable[Resource], *types: str) -> list[Resource]:
    return [r for r in resources if r.type in types]


def check_s3_public_access_block(resources: list[Resource]) -> list[Finding]:
    findings = []
    pabs = _of_type(resources, "aws_s3_bucket_public_access_block")
    for pab in pabs:
        off = [f for f in PAB_FLAGS if pab.after.get(f) is not True]
        if off:
            findings.append(Finding("CSP-S3-001", "HIGH", pab.address, f"public access block has {', '.join(off)} not true"))
    for bucket in _of_type(resources, "aws_s3_bucket"):
        if not any(_references(p, "bucket", bucket) for p in pabs):
            findings.append(Finding("CSP-S3-001", "HIGH", bucket.address, "bucket has no aws_s3_bucket_public_access_block"))
    return findings


def _port_in_range(port: int, from_port: Any, to_port: Any, protocol: Any) -> bool:
    if str(protocol) in ("-1", "all"):
        return True
    if str(protocol).lower() not in ("tcp", "6"):
        return False
    try:
        return int(from_port) <= port <= int(to_port)
    except (TypeError, ValueError):
        return False


def _open_admin_ports(cidrs: Iterable[str], from_port: Any, to_port: Any, protocol: Any) -> list[str]:
    hits = []
    for cidr in cidrs:
        if cidr in OPEN_CIDRS:
            for port in ADMIN_PORTS:
                if _port_in_range(port, from_port, to_port, protocol):
                    hits.append(f"{cidr} on port {port}")
    return hits


def check_security_groups(resources: list[Resource]) -> list[Finding]:
    findings = []

    def add(res: Resource, hits: list[str], where: str = "") -> None:
        if hits:
            findings.append(Finding("CSP-SG-001", "HIGH", res.address, f"ingress{where} allows {'; '.join(hits)}"))

    for sg in _of_type(resources, "aws_security_group"):
        for i, rule in enumerate(sg.after.get("ingress") or []):
            cidrs = list(rule.get("cidr_blocks") or []) + list(rule.get("ipv6_cidr_blocks") or [])
            add(sg, _open_admin_ports(cidrs, rule.get("from_port"), rule.get("to_port"), rule.get("protocol")), f"[{i}]")

    for rule in _of_type(resources, "aws_security_group_rule"):
        if rule.after.get("type") != "ingress":
            continue
        cidrs = list(rule.after.get("cidr_blocks") or []) + list(rule.after.get("ipv6_cidr_blocks") or [])
        add(rule, _open_admin_ports(cidrs, rule.after.get("from_port"), rule.after.get("to_port"), rule.after.get("protocol")))

    for rule in _of_type(resources, "aws_vpc_security_group_ingress_rule"):
        cidrs = [c for c in (rule.after.get("cidr_ipv4"), rule.after.get("cidr_ipv6")) if c]
        add(rule, _open_admin_ports(cidrs, rule.after.get("from_port"), rule.after.get("to_port"), rule.after.get("ip_protocol")))
    return findings


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def check_iam_wildcard(resources: list[Resource]) -> list[Finding]:
    findings = []
    for res in _of_type(resources, *IAM_POLICY_TYPES):
        raw = res.after.get("policy")
        if not raw:
            continue  # unknown until apply (computed from a data source): cannot judge
        try:
            doc = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            findings.append(Finding("CSP-IAM-001", "HIGH", res.address, "policy is not valid JSON; cannot verify it"))
            continue
        for i, stmt in enumerate(_as_list(doc.get("Statement") if isinstance(doc, dict) else None)):
            if not isinstance(stmt, dict) or stmt.get("Effect") != "Allow":
                continue
            if "*" in _as_list(stmt.get("Action")) and "*" in _as_list(stmt.get("Resource")):
                sid = stmt.get("Sid")
                label = f"Sid {sid!r}" if sid else f"statement {i}"
                findings.append(Finding("CSP-IAM-001", "HIGH", res.address, f"{label} allows Action \"*\" on Resource \"*\""))
    return findings


def check_rds_encryption(resources: list[Resource]) -> list[Finding]:
    findings = []
    for res in _of_type(resources, "aws_db_instance", "aws_rds_cluster"):
        if res.after.get("storage_encrypted") is not True:
            findings.append(Finding("CSP-RDS-001", "HIGH", res.address, f"storage_encrypted is {json.dumps(res.after.get('storage_encrypted'))}"))
    return findings


def check_cloudtrail_validation(resources: list[Resource]) -> list[Finding]:
    findings = []
    for res in _of_type(resources, "aws_cloudtrail"):
        if res.after.get("enable_log_file_validation") is not True:
            findings.append(Finding("CSP-CT-001", "MEDIUM", res.address, "enable_log_file_validation is not true"))
    return findings


def check_public_alb_waf(resources: list[Resource]) -> list[Finding]:
    findings = []
    assocs = _of_type(resources, "aws_wafv2_web_acl_association")
    for lb in _of_type(resources, "aws_lb", "aws_alb"):
        if lb.after.get("load_balancer_type", "application") != "application":
            continue
        if lb.after.get("internal") is True:
            continue
        if not any(_references(a, "resource_arn", lb) for a in assocs):
            findings.append(Finding("CSP-WAF-001", "MEDIUM", lb.address, "internet-facing ALB has no WAF web ACL association"))
    return findings


CHECKS: list[Callable[[list[Resource]], list[Finding]]] = [
    check_s3_public_access_block,
    check_security_groups,
    check_iam_wildcard,
    check_rds_encryption,
    check_cloudtrail_validation,
    check_public_alb_waf,
]


# ----------------------------------------------------------------------------- exceptions


def load_exceptions(path: Path | None) -> list[dict]:
    if path is None:
        return []
    data = load_json(path, "exceptions file")
    entries = data.get("exceptions") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise InputError(f"exceptions file must be an object with an 'exceptions' list: {path}")
    parsed = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise InputError(f"exception #{i} is not an object")
        missing = [k for k in ("rule_id", "resource", "owner", "reason", "expires") if not str(e.get(k, "")).strip()]
        if missing:
            raise InputError(f"exception #{i} is missing {', '.join(missing)}")
        if e["rule_id"] not in RULES:
            raise InputError(f"exception #{i} names unknown rule {e['rule_id']!r}")
        try:
            expires = dt.date.fromisoformat(e["expires"])
        except ValueError as exc:
            raise InputError(f"exception #{i} expires must be YYYY-MM-DD, got {e['expires']!r}") from exc
        parsed.append({**e, "_expires": expires})
    return parsed


def apply_exceptions(findings: list[Finding], exceptions: list[dict], today: dt.date) -> tuple[list[dict], list[dict]]:
    """Mark excepted findings. Returns (expired, unused). An exception is
    valid through its expiry date inclusive."""
    expired = [e for e in exceptions if e["_expires"] < today]
    valid = [e for e in exceptions if e["_expires"] >= today]
    used: set[int] = set()
    for f in findings:
        for idx, e in enumerate(valid):
            if e["rule_id"] == f.rule_id and e["resource"] == f.address:
                f.excepted_by = e
                used.add(idx)
                break
    unused = [e for idx, e in enumerate(valid) if idx not in used]
    return expired, unused


# ----------------------------------------------------------------------------- evaluation


def evaluate(plan: Any, plan_path: str, exceptions: list[dict], today: dt.date) -> Report:
    resources = load_resources(plan)
    findings: list[Finding] = []
    for check in CHECKS:
        findings.extend(check(resources))
    order = list(RULES)
    findings.sort(key=lambda f: (SEVERITIES.index(f.severity), order.index(f.rule_id), f.address))
    expired, unused = apply_exceptions(findings, exceptions, today)
    return Report(plan_path, len(resources), findings, expired, unused)


# ----------------------------------------------------------------------------- output


def _public(e: dict) -> dict:
    return {k: v for k, v in e.items() if not k.startswith("_")}


def render_text(report: Report) -> str:
    lines = [f"{TOOL_NAME}: {report.plan_path}: {report.resources_checked} resources, {len(RULES)} rules"]
    for f in report.active:
        rule = RULES[f.rule_id]
        lines.append(f"FAIL {f.severity:<6} {f.rule_id:<12} {f.address}: {f.message}")
        lines.append(f"     fix: {rule.remediation}")
    for f in report.excepted:
        e = f.excepted_by or {}
        lines.append(f"EXCEPTED {f.rule_id}  {f.address} (owner {e['owner']}, until {e['expires']}): {e['reason']}")
    for e in report.expired_exceptions:
        lines.append(f"EXPIRED  exception for {e['rule_id']} on {e['resource']} (owner {e['owner']}) expired {e['expires']}: ignored")
    for e in report.unused_exceptions:
        lines.append(f"UNUSED   exception for {e['rule_id']} on {e['resource']} matched no finding (owner {e['owner']})")
    counts = {s: sum(1 for f in report.active if f.severity == s) for s in SEVERITIES}
    by_sev = ", ".join(f"{counts[s]} {s}" for s in SEVERITIES if counts[s]) or "none"
    lines.append(
        f"Summary: {len(report.active)} finding(s) ({by_sev}), {len(report.excepted)} excepted, "
        f"{len(report.expired_exceptions)} expired exception(s). Result: {'FAIL' if report.failed else 'PASS'}"
    )
    return "\n".join(lines)


def _line_of(plan_text: str, address: str) -> int:
    needle = f'"address": "{address}"'
    idx = plan_text.find(needle)
    if idx < 0:
        needle = f'"address":"{address}"'
        idx = plan_text.find(needle)
    return plan_text.count("\n", 0, idx) + 1 if idx >= 0 else 1


def render_sarif(report: Report, plan_text: str, artifact_uri: str) -> dict:
    rule_ids = list(RULES)
    rules = [
        {
            "id": r.id,
            "name": r.name,
            "shortDescription": {"text": r.title},
            "fullDescription": {"text": f"{r.title}. Severity {r.severity}."},
            "help": {"text": r.remediation, "markdown": f"**Remediation:** {r.remediation}"},
            "defaultConfiguration": {"level": SARIF_LEVEL[r.severity]},
            "properties": {"security-severity": SECURITY_SEVERITY[r.severity], "tags": ["security", "terraform", "aws"]},
        }
        for r in RULES.values()
    ]
    results = []
    for f in report.findings:
        result: dict[str, Any] = {
            "ruleId": f.rule_id,
            "ruleIndex": rule_ids.index(f.rule_id),
            "level": SARIF_LEVEL[f.severity],
            "message": {"text": f"{f.address}: {f.message}"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": artifact_uri},
                        "region": {"startLine": _line_of(plan_text, f.address)},
                    },
                    "logicalLocations": [{"fullyQualifiedName": f.address, "kind": "resource"}],
                }
            ],
            "partialFingerprints": {
                "checkPlanFinding/v1": hashlib.sha256(f"{f.rule_id}|{f.address}".encode()).hexdigest()
            },
        }
        if f.excepted_by is not None:
            e = f.excepted_by
            result["suppressions"] = [
                {"kind": "external", "status": "accepted", "justification": f"{e['reason']} (owner {e['owner']}, expires {e['expires']})"}
            ]
        results.append(result)
    notifications = [
        {"level": "warning", "message": {"text": f"expired exception ignored: {e['rule_id']} on {e['resource']} (owner {e['owner']}, expired {e['expires']})"}}
        for e in report.expired_exceptions
    ]
    run: dict[str, Any] = {
        "tool": {"driver": {"name": TOOL_NAME, "version": TOOL_VERSION, "informationUri": TOOL_URI, "rules": rules}},
        "results": results,
    }
    if notifications:
        run["invocations"] = [{"executionSuccessful": True, "toolExecutionNotifications": notifications}]
    return {"$schema": SARIF_SCHEMA, "version": "2.1.0", "runs": [run]}


# ----------------------------------------------------------------------------- CLI


def default_exceptions_path() -> Path | None:
    path = Path(__file__).resolve().parent / "exceptions.json"
    return path if path.exists() else None


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate security policy rules against `terraform show -json` output.")
    p.add_argument("plan", help="plan JSON file (terraform show -json tfplan > plan.json)")
    p.add_argument("--format", choices=("text", "sarif"), default="text")
    p.add_argument("--output", "-o", help="write the report here instead of stdout")
    p.add_argument("--exceptions", help="exceptions JSON (default: policy/exceptions.json if present)")
    p.add_argument("--no-exceptions", action="store_true", help="ignore every exception")
    p.add_argument("--today", help="evaluation date YYYY-MM-DD for exception expiry (default: today, UTC)")
    p.add_argument("--artifact-uri", help="file URI in SARIF results, relative to the repository root (default: the plan path as given)")
    p.add_argument("--list-rules", action="store_true", help="print the rules and exit")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--list-rules" in argv:
        for r in RULES.values():
            print(f"{r.id:<12} {r.severity:<6} {r.title}")
        return 0
    args = parse_args(argv)
    try:
        today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    except ValueError:
        print(f"error: --today must be YYYY-MM-DD, got {args.today!r}", file=sys.stderr)
        return 2
    try:
        plan_path = Path(args.plan)
        plan = load_json(plan_path, "plan")
        exc_path = None if args.no_exceptions else (Path(args.exceptions) if args.exceptions else default_exceptions_path())
        exceptions = load_exceptions(exc_path)
        report = evaluate(plan, args.plan, exceptions, today)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "sarif":
        out = json.dumps(render_sarif(report, plan_path.read_text(encoding="utf-8"), args.artifact_uri or args.plan), indent=2)
    else:
        out = render_text(report)
    if args.output:
        Path(args.output).write_text(out + "\n", encoding="utf-8")
        print(f"{TOOL_NAME}: wrote {args.format} report to {args.output} ({'FAIL' if report.failed else 'PASS'})")
    else:
        print(out)
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
