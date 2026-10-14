#!/usr/bin/env python3
"""Teaching approximation of SCP evaluation for one request.

Given an OU, an action, a region and a principal, report whether the SCPs
on the path from the organization root to that OU would deny the request.

THIS IS NOT THE IAM POLICY SIMULATOR. It models only what the shipped
policies use, to make the guardrails explainable and testable offline:

- SCPs from every level of the OU path (root, parent OUs, the OU). An
  explicit Deny anywhere wins. Each level must also have an Allow that
  matches (FullAWSAccess, modelled as Allow * on *), otherwise the request is
  implicitly denied at that level.
- ``Action`` / ``NotAction`` with ``*`` and ``?`` wildcards, case-insensitive.
- Condition operators StringEquals, StringNotEquals, StringLike,
  StringNotLike, ArnEquals, ArnLike, ArnNotLike, Bool and Null, each with an
  optional ``IfExists`` suffix. Multiple keys in one operator and multiple
  operators in one block are ANDed; multiple values for a key are ORed. A
  missing key makes a positive operator false and a negated operator true,
  as IAM does. Anything else (set operators, Numeric*, Date*, IpAddress,
  policy variables) raises an error instead of guessing.
- ``Resource`` is ignored unless ``--resource`` is given: by default every
  statement is assumed to match the resource the request touches.

Not modelled: identity and resource policies, permission boundaries,
session policies, service-linked roles (which SCPs never restrict), the
management account (which SCPs never restrict), and the multi-resource
authorization of calls such as ec2:RunInstances.

Exit codes: 0 not denied by SCPs (IAM policies still decide), 1 denied,
2 bad input.

Standard library only.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_scps  # noqa: E402  (shared loading and wildcard helpers)
from check_scps import InputError, action_matches, as_list  # noqa: E402

FULL_AWS_ACCESS = {
    "Version": "2012-10-17",
    "Statement": [{"Sid": "FullAWSAccess", "Effect": "Allow", "Action": "*", "Resource": "*"}],
}
DEFAULT_ACCOUNT = "123456789012"
DEFAULT_ROLE = "role/developer"


class UnsupportedCondition(Exception):
    """A condition operator the simulator does not model: exit code 2."""


# ----------------------------------------------------------------------------- conditions


def _string_equals(actual: str, expected: str) -> bool:
    return actual == expected


def _string_like(actual: str, expected: str) -> bool:
    # IAM *Like operators: case-sensitive, * and ? wildcards.
    return fnmatch.fnmatchcase(actual, expected.replace("[", "[[]"))


def _arn_like(actual: str, expected: str) -> bool:
    # IAM checks each of the six colon-delimited ARN components separately,
    # so a wildcard never spans a colon.
    a, e = actual.split(":", 5), expected.split(":", 5)
    return len(a) == len(e) == 6 and all(_string_like(x, y) for x, y in zip(a, e))


def _bool(actual: str, expected: str) -> bool:
    return actual.lower() == expected.lower()


POSITIVE = {
    "StringEquals": _string_equals,
    "StringLike": _string_like,
    "ArnEquals": _arn_like,
    "ArnLike": _arn_like,
    "Bool": _bool,
}
NEGATED = {
    "StringNotEquals": "StringEquals",
    "StringNotLike": "StringLike",
    "ArnNotEquals": "ArnEquals",
    "ArnNotLike": "ArnLike",
}
SUPPORTED_OPERATORS = sorted([*POSITIVE, *NEGATED, "Null"])


def _lookup(context: dict[str, list[str]], key: str) -> list[str] | None:
    # Condition keys are case-insensitive; values are not.
    for k, v in context.items():
        if k.lower() == key.lower():
            return v
    return None


def condition_operator_supported(operator: str) -> bool:
    base = operator[:-len("IfExists")] if operator.endswith("IfExists") else operator
    return base in POSITIVE or base in NEGATED or base == "Null"


def evaluate_operator(operator: str, keys: dict[str, Any], context: dict[str, list[str]]) -> bool:
    if_exists = operator.endswith("IfExists")
    base = operator[:-len("IfExists")] if if_exists else operator
    if not condition_operator_supported(operator) or (base == "Null" and if_exists):
        raise UnsupportedCondition(f"condition operator {operator!r} is not modelled (supported: {SUPPORTED_OPERATORS})")
    for key, expected in keys.items():
        expected_values = [str(e) for e in as_list(expected)]
        actual = _lookup(context, key)
        if base == "Null":
            want_absent = expected_values[0].lower() == "true"
            ok = (actual is None) == want_absent
        elif actual is None:
            ok = if_exists or base in NEGATED
        elif base in NEGATED:
            fn = POSITIVE[NEGATED[base]]
            ok = not any(fn(a, e) for a in actual for e in expected_values)
        else:
            fn = POSITIVE[base]
            ok = any(fn(a, e) for a in actual for e in expected_values)
        if not ok:
            return False
    return True


def conditions_match(condition: dict | None, context: dict[str, list[str]]) -> bool:
    return all(evaluate_operator(op, keys, context) for op, keys in (condition or {}).items())


# ----------------------------------------------------------------------------- statements


@dataclass(frozen=True)
class Request:
    action: str
    region: str
    principal_arn: str
    resource: str | None = None
    extra_context: tuple[tuple[str, str], ...] = ()

    def context(self) -> dict[str, list[str]]:
        ctx: dict[str, list[str]] = {
            "aws:RequestedRegion": [self.region],
            "aws:PrincipalArn": [self.principal_arn],
        }
        for key, value in self.extra_context:
            existing = _lookup(ctx, key)
            if existing is None:
                ctx[key] = [value]
            else:
                existing.append(value)
        return ctx


def statement_applies(stmt: dict, request: Request, context: dict[str, list[str]]) -> bool:
    if "Action" in stmt:
        if not any(action_matches(p, request.action) for p in as_list(stmt["Action"])):
            return False
    elif "NotAction" in stmt:
        if any(action_matches(p, request.action) for p in as_list(stmt["NotAction"])):
            return False
    else:
        return False
    if request.resource is not None:
        if "Resource" in stmt and not any(action_matches(p, request.resource) for p in as_list(stmt["Resource"])):
            return False
        if "NotResource" in stmt and any(action_matches(p, request.resource) for p in as_list(stmt["NotResource"])):
            return False
    return conditions_match(stmt.get("Condition"), context)


# ----------------------------------------------------------------------------- evaluation


@dataclass
class Match:
    level: str
    policy: str
    sid: str
    effect: str


@dataclass
class Result:
    request: Request
    ou: str
    path: list[str]
    attached: dict[str, list[str]]
    denies: list[Match] = field(default_factory=list)
    allows: list[Match] = field(default_factory=list)
    levels_without_allow: list[str] = field(default_factory=list)

    @property
    def denied(self) -> bool:
        return bool(self.denies or self.levels_without_allow)


def ou_path(hierarchy: dict[str, str | None], ou: str) -> list[str]:
    if ou not in hierarchy:
        raise InputError(f"unknown OU {ou!r}; known: {', '.join(hierarchy)}")
    path, node, seen = [], ou, set()
    while node is not None:
        if node in seen:
            raise InputError(f"cycle in OU hierarchy at {node!r}")
        seen.add(node)
        path.append(node)
        node = hierarchy.get(node)
    return list(reversed(path))


@dataclass
class PolicySet:
    documents: dict[str, dict]
    hierarchy: dict[str, str | None]
    attachments: dict[str, list[str]]


def load_policy_set(scp_dir: Path = check_scps.DEFAULT_SCP_DIR,
                    attachments_path: Path = check_scps.DEFAULT_ATTACHMENTS,
                    template_values_path: Path | None = check_scps.DEFAULT_TEMPLATE_VALUES) -> PolicySet:
    values = check_scps.load_template_values(template_values_path)
    policies, problems = check_scps.load_policies(scp_dir, values)
    if problems:
        raise InputError("; ".join(f"{p.subject}: {p.message}" for p in problems))
    documents = {p.name: p.document for p in policies if p.document is not None}
    documents["FullAWSAccess"] = FULL_AWS_ACCESS
    amap = check_scps.load_attachments(attachments_path)
    for target, names in amap["attachments"].items():
        for name in names:
            if name not in documents:
                raise InputError(f"{target}: attached SCP {name!r} has no policy file")
    return PolicySet(documents, amap["hierarchy"], amap["attachments"])


def simulate(policy_set: PolicySet, ou: str, request: Request) -> Result:
    path = ou_path(policy_set.hierarchy, ou)
    context = request.context()
    result = Result(request, ou, path, {lvl: policy_set.attachments.get(lvl, []) for lvl in path})
    for level in path:
        level_allows = False
        for name in policy_set.attachments.get(level, []):
            for i, stmt in enumerate(check_scps.statements(policy_set.documents[name])):
                if not statement_applies(stmt, request, context):
                    continue
                match = Match(level, name, stmt.get("Sid") or f"Statement[{i}]", stmt.get("Effect", ""))
                if match.effect == "Deny":
                    result.denies.append(match)
                elif match.effect == "Allow":
                    result.allows.append(match)
                    level_allows = True
        if not level_allows:
            result.levels_without_allow.append(level)
    return result


def principal_for(root: bool, principal_arn: str | None) -> str:
    if principal_arn:
        return principal_arn
    return f"arn:aws:iam::{DEFAULT_ACCOUNT}:root" if root else f"arn:aws:iam::{DEFAULT_ACCOUNT}:{DEFAULT_ROLE}"


def format_text(result: Result) -> str:
    r = result.request
    width = max(len(lvl) for lvl in result.path)
    lines = [
        f"request:   {r.action} in {r.region}" + (f" on {r.resource}" if r.resource else ""),
        f"principal: {r.principal_arn}",
    ]
    for key, value in r.extra_context:
        lines.append(f"context:   {key}={value}")
    lines.append(f"OU path:   {' > '.join(result.path)}")
    for level in result.path:
        lines.append(f"  {level:<{width}}  {', '.join(result.attached[level]) or '(nothing attached)'}")
    for m in result.denies:
        lines.append(f"DENY   {m.policy}/{m.sid} (attached to {m.level})")
    for level in result.levels_without_allow:
        lines.append(f"DENY   implicit: no SCP attached to {level} allows the action")
    if result.denied:
        reasons = len(result.denies) + len(result.levels_without_allow)
        lines.append(f"Result: DENIED by SCPs ({reasons} reason(s))")
    else:
        lines.append("Result: NOT DENIED by SCPs (identity and resource policies still decide)")
    return "\n".join(lines)


def parse_context(items: list[str]) -> tuple[tuple[str, str], ...]:
    out = []
    for item in items:
        if "=" not in item:
            raise InputError(f"--context expects KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        out.append((key.strip(), value))
    return tuple(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Teaching approximation of SCP evaluation (not the IAM policy simulator).")
    parser.add_argument("--ou", required=True, help="OU key from the attachment map, e.g. prod, sandbox, suspended")
    parser.add_argument("--action", required=True, help="service:Action, e.g. ec2:RunInstances")
    parser.add_argument("--region", required=True, help="requested region, e.g. eu-west-1")
    parser.add_argument("--root", action="store_true", help="the caller is the account root user")
    parser.add_argument("--principal-arn", help="override the caller ARN")
    parser.add_argument("--resource", help="resource ARN; omitted means every statement's Resource matches")
    parser.add_argument("--context", action="append", default=[], metavar="KEY=VALUE",
                        help="extra condition key, repeatable (e.g. ec2:MetadataHttpTokens=required)")
    parser.add_argument("--scp-dir", type=Path, default=check_scps.DEFAULT_SCP_DIR)
    parser.add_argument("--attachments", type=Path, default=check_scps.DEFAULT_ATTACHMENTS)
    parser.add_argument("--template-values", type=Path, default=check_scps.DEFAULT_TEMPLATE_VALUES)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2

    try:
        request = Request(args.action, args.region, principal_for(args.root, args.principal_arn),
                          args.resource, parse_context(args.context))
        result = simulate(load_policy_set(args.scp_dir, args.attachments, args.template_values), args.ou, request)
    except (InputError, UnsupportedCondition) as exc:
        print(f"simulate_scp: error: {exc}", file=sys.stderr)
        return 2
    print(format_text(result))
    return 1 if result.denied else 0


if __name__ == "__main__":
    sys.exit(main())
