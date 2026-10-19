"""Render a PipelineResult as text, markdown or JSON."""

from __future__ import annotations

import json

from .models import to_jsonable
from .pipeline import PipelineResult


def to_text(result: PipelineResult) -> str:
    if not result.items:
        return "No anomalies detected.\n"
    lines = [f"{len(result.items)} anomaly/anomalies detected.\n"]
    for item in result.items:
        a = item.correlation.anomaly
        lines.append(
            f"[{a.service}] {a.window_start.isoformat()} z={a.z_score:.2f} "
            f"observed={a.observed_value:.1%} baseline={a.baseline_mean:.1%}+/-{a.baseline_stddev:.1%}"
        )
        lines.append(f"  summary ({item.summary.source}): {item.summary.text}")
        lines.append(
            f"  proposal {item.proposal.id}: {item.proposal.action} "
            f"(allowed={item.proposal.allowed}) -- {item.proposal.rationale}"
        )
        lines.append("")
    return "\n".join(lines)


def to_markdown(result: PipelineResult) -> str:
    if not result.items:
        return "## AI Cloud Operations report\n\nNo anomalies detected.\n"
    lines = ["## AI Cloud Operations report", "", f"{len(result.items)} anomaly/anomalies detected.", ""]
    lines.append("| Service | Window start | z-score | Observed | Baseline | Action | Allowed | Proposal id |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for item in result.items:
        a = item.correlation.anomaly
        p = item.proposal
        lines.append(
            f"| {a.service} | {a.window_start.isoformat()} | {a.z_score:.2f} | "
            f"{a.observed_value:.1%} | {a.baseline_mean:.1%}+/-{a.baseline_stddev:.1%} | "
            f"{p.action} | {p.allowed} | `{p.id}` |"
        )
    lines.append("")
    for item in result.items:
        lines.append(f"### {item.correlation.anomaly.service} - {item.proposal.id}")
        lines.append(f"- Summary ({item.summary.source}): {item.summary.text}")
        lines.append(f"- Rationale: {item.proposal.rationale}")
        lines.append("")
    return "\n".join(lines)


def to_json(result: PipelineResult) -> str:
    return json.dumps(to_jsonable(result), indent=2, sort_keys=True)
