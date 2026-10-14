#!/usr/bin/env python3
"""Summarise AWS WAF logs (JSON lines) for the count-then-block rollout.

Reads WAF log records, one JSON object per line (CloudWatch Logs export,
S3/Firehose delivery or `aws logs filter-log-events` output reduced to the
message field), and prints:

  * actions: how many requests were allowed, blocked, counted;
  * top blocked rules, including the rule inside a managed rule group;
  * top client IPs by blocked requests;
  * count-mode matches that would have blocked: the "should I flip this
    rule to block?" view, with how many requests would *newly* be blocked
    (the request was otherwise allowed), how many distinct clients that
    hits, and which URI dominates.

Standard library only. Malformed lines are skipped and counted.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, TextIO

BLOCKING_ACTIONS = {"BLOCK"}


@dataclass
class CountRuleStats:
    rule: str
    kind: str  # "count-mode rule", "count-mode group", "rule override"
    matches: int = 0
    newly_blocked: int = 0
    ips: Counter = field(default_factory=Counter)
    uris: Counter = field(default_factory=Counter)

    def hint(self) -> str:
        if self.newly_blocked == 0:
            return "no change: every match was already blocked by another rule"
        unique = len(self.ips)
        top_uri_share = self.uris.most_common(1)[0][1] / self.newly_blocked if self.uris else 0.0
        if unique <= 2:
            return "concentrated on few clients: likely hostile, candidate to block"
        if top_uri_share >= 0.6:
            return "many clients on one path: check for a false positive (scope-down or exclusion) first"
        return "mixed: review sampled requests before blocking"

    def as_dict(self, top: int) -> dict[str, Any]:
        top_uri = self.uris.most_common(1)
        return {
            "rule": self.rule,
            "kind": self.kind,
            "matches": self.matches,
            "would_newly_block": self.newly_blocked,
            "unique_client_ips": len(self.ips),
            "top_client_ips": [{"ip": ip, "requests": n} for ip, n in self.ips.most_common(top)],
            "top_uri": {"uri": top_uri[0][0], "requests": top_uri[0][1]} if top_uri else None,
            "hint": self.hint(),
        }


@dataclass
class Summary:
    total: int = 0
    malformed: int = 0
    first_ts: int | None = None
    last_ts: int | None = None
    actions: Counter = field(default_factory=Counter)
    blocked_rules: Counter = field(default_factory=Counter)
    blocked_ips: Counter = field(default_factory=Counter)
    ip_totals: Counter = field(default_factory=Counter)
    count_rules: dict[str, CountRuleStats] = field(default_factory=dict)

    def count_rule(self, rule: str, kind: str) -> CountRuleStats:
        key = f"{kind}:{rule}"
        if key not in self.count_rules:
            self.count_rules[key] = CountRuleStats(rule, kind)
        return self.count_rules[key]


def _group_name(rule_group_id: str) -> str:
    """'AWS#AWSManagedRulesCommonRuleSet' -> 'AWSManagedRulesCommonRuleSet'."""
    return rule_group_id.split("#")[-1] if rule_group_id else "unknown-group"


def blocked_rule_label(record: dict) -> str:
    """Terminating rule, plus the inner rule when a managed group blocked."""
    rule_id = record.get("terminatingRuleId") or "unknown"
    if record.get("terminatingRuleType") == "MANAGED_RULE_GROUP":
        for group in record.get("ruleGroupList") or []:
            term = (group or {}).get("terminatingRule") or {}
            if term.get("action") in BLOCKING_ACTIONS and term.get("ruleId"):
                return f"{rule_id}/{term['ruleId']}"
    return rule_id


def would_block_matches(record: dict) -> list[tuple[str, str]]:
    """(rule label, kind) for every match that is in count mode now but would
    block once flipped. Covers three cases in the WAF log schema:

    * a custom rule with action COUNT: top-level nonTerminatingMatchingRules;
    * a managed rule group with override_action count: the group's entry in
      ruleGroupList has a terminatingRule with action BLOCK, but the request
      was not terminated by that group;
    * a rule inside a group overridden to COUNT (rule_action_override): the
      group's nonTerminatingMatchingRules entry carries overriddenAction BLOCK.
    """
    out: list[tuple[str, str]] = []
    group_rule_names: set[str] = set()
    terminating = record.get("terminatingRuleId")

    for group in record.get("ruleGroupList") or []:
        group = group or {}
        gname = _group_name(group.get("ruleGroupId", ""))
        term = group.get("terminatingRule") or {}
        # When this group terminated the request it is not in count mode.
        terminated_here = record.get("terminatingRuleType") == "MANAGED_RULE_GROUP" and terminating and terminating.endswith(gname)
        if term.get("action") in BLOCKING_ACTIONS and term.get("ruleId") and not terminated_here:
            out.append((f"{gname}/{term['ruleId']}", "count-mode group"))
            group_rule_names.add(gname)
        for match in group.get("nonTerminatingMatchingRules") or []:
            match = match or {}
            if match.get("action") == "COUNT" and match.get("overriddenAction") in BLOCKING_ACTIONS:
                out.append((f"{gname}/{match.get('ruleId', 'unknown')}", "rule override"))

    for match in record.get("nonTerminatingMatchingRules") or []:
        match = match or {}
        rule_id = match.get("ruleId", "")
        if match.get("action") != "COUNT":
            continue
        # The group-level COUNT entry duplicates the inner rule already recorded.
        if any(rule_id.endswith(g) for g in group_rule_names):
            continue
        out.append((rule_id or "unknown", "count-mode rule"))
    return out


def summarise(lines: Iterable[str]) -> Summary:
    s = Summary()
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            s.malformed += 1
            continue
        if not isinstance(record, dict) or "action" not in record:
            s.malformed += 1
            continue

        s.total += 1
        action = str(record.get("action"))
        s.actions[action] += 1
        request = record.get("httpRequest") or {}
        ip = request.get("clientIp") or "unknown"
        uri = request.get("uri") or "/"
        s.ip_totals[ip] += 1

        ts = record.get("timestamp")
        if isinstance(ts, int):
            s.first_ts = ts if s.first_ts is None else min(s.first_ts, ts)
            s.last_ts = ts if s.last_ts is None else max(s.last_ts, ts)

        if action in BLOCKING_ACTIONS:
            s.blocked_rules[blocked_rule_label(record)] += 1
            s.blocked_ips[ip] += 1

        for rule, kind in would_block_matches(record):
            stats = s.count_rule(rule, kind)
            stats.matches += 1
            if action not in BLOCKING_ACTIONS:
                stats.newly_blocked += 1
                stats.ips[ip] += 1
                stats.uris[uri] += 1
    return s


def _iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sorted_count_rules(s: Summary) -> list[CountRuleStats]:
    return sorted(s.count_rules.values(), key=lambda r: (-r.newly_blocked, -r.matches, r.rule))


def to_dict(s: Summary, top: int) -> dict[str, Any]:
    return {
        "records": s.total,
        "malformed_lines": s.malformed,
        "window": {"first": _iso(s.first_ts), "last": _iso(s.last_ts)},
        "actions": dict(sorted(s.actions.items())),
        "top_blocked_rules": [{"rule": r, "requests": n} for r, n in s.blocked_rules.most_common(top)],
        "top_blocked_client_ips": [
            {"ip": ip, "blocked": n, "total": s.ip_totals[ip]} for ip, n in s.blocked_ips.most_common(top)
        ],
        "count_mode_would_block": [r.as_dict(top) for r in _sorted_count_rules(s)],
    }


def render_text(s: Summary, top: int) -> str:
    lines = [f"WAF log summary: {s.total} records ({_iso(s.first_ts)} .. {_iso(s.last_ts)})"]
    if s.malformed:
        lines.append(f"skipped {s.malformed} malformed line(s)")
    lines.append("Actions: " + ", ".join(f"{a} {n}" for a, n in sorted(s.actions.items())))
    blocked = s.actions.get("BLOCK", 0)

    lines.append("")
    lines.append(f"Top blocked rules ({blocked} blocked):")
    for rule, n in s.blocked_rules.most_common(top):
        share = 100 * n / blocked if blocked else 0
        lines.append(f"  {n:>5}  {share:5.1f}%  {rule}")
    if not s.blocked_rules:
        lines.append("  (none)")

    lines.append("")
    lines.append("Top client IPs by blocked requests:")
    for ip, n in s.blocked_ips.most_common(top):
        lines.append(f"  {n:>5} blocked / {s.ip_totals[ip]:>5} total  {ip}")
    if not s.blocked_ips:
        lines.append("  (none)")

    lines.append("")
    lines.append("Count-mode matches that would block (flip-to-block review):")
    rules = _sorted_count_rules(s)
    for r in rules:
        top_uri = r.uris.most_common(1)
        uri_txt = f"{top_uri[0][0]} ({top_uri[0][1]}/{r.newly_blocked})" if top_uri else "-"
        lines.append(f"  {r.rule}  [{r.kind}]")
        lines.append(
            f"      matches {r.matches}, would newly block {r.newly_blocked}, "
            f"unique IPs {len(r.ips)}, top URI {uri_txt}"
        )
        lines.append(f"      hint: {r.hint()}")
    if not rules:
        lines.append("  (none)")
    return "\n".join(lines)


def _open(path: str) -> TextIO:
    return sys.stdin if path == "-" else open(path, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Summarise AWS WAF JSON-lines logs.")
    p.add_argument("logfile", nargs="+", help="WAF log file(s), JSON lines; '-' for stdin")
    p.add_argument("--top", type=int, default=5, help="rows per table (default 5)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)
    if args.top < 1:
        print("error: --top must be at least 1", file=sys.stderr)
        return 2

    def lines() -> Iterable[str]:
        for path in args.logfile:
            with _open(path) as fh:
                yield from fh

    try:
        summary = summarise(lines())
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if summary.total == 0:
        print("error: no WAF log records found", file=sys.stderr)
        return 2
    print(json.dumps(to_dict(summary, args.top), indent=2) if args.json else render_text(summary, args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
