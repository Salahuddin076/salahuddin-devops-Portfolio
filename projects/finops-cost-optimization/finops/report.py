"""Render analysis results as plain text, Markdown, or self-contained HTML.

Every analysis is first turned into a small list of *blocks* (heading,
paragraph, bullet list, table). The CLI prints blocks as text; ``report``
renders the same blocks to Markdown and HTML, so all three outputs agree.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from .allocation import AllocationResult
from .budget import BudgetResult
from .commitments import CommitmentResult
from .forecast import ForecastResult
from .models import to_jsonable
from .rightsizing import RightsizeResult

DISCLAIMER = (
    "Synthetic data, illustrative prices (approximate us-east-1 on-demand list "
    "prices - verify against current AWS pricing). No real savings are claimed."
)


@dataclass(frozen=True)
class Heading:
    text: str
    level: int = 2


@dataclass(frozen=True)
class Para:
    text: str


@dataclass(frozen=True)
class Bullets:
    items: Sequence[str]


@dataclass(frozen=True)
class Table:
    headers: Sequence[str]
    rows: Sequence[Sequence[str]]


Block = Heading | Para | Bullets | Table


def usd(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _pct(value: Decimal) -> str:
    return f"{value}%"


# --------------------------------------------------------------------------- sections


def allocation_blocks(res: AllocationResult) -> list[Block]:
    blocks: list[Block] = [
        Heading("Cost allocation (showback)"),
        Para(
            f"Total {res.cost_column} cost: {usd(res.total)}. Spend with none of the "
            f"allocation tags: {usd(res.no_tags_at_all.cost)} ({_pct(res.no_tags_at_all.pct)})."
        ),
        Table(
            ["Tag key", "Untagged cost", "Untagged %"],
            [[k, usd(s.cost), _pct(s.pct)] for k, s in res.untagged_by_key.items()],
        ),
    ]
    for key, shares in res.by_key.items():
        blocks.append(Heading(f"By `{key}`", 3))
        blocks.append(Table([key, "Cost", "%"], [[s.name, usd(s.cost), _pct(s.pct)] for s in shares]))
    blocks.append(Heading("Top services", 3))
    blocks.append(Table(["Service", "Cost", "%"], [[s.name, usd(s.cost), _pct(s.pct)] for s in res.top_services]))
    if res.top_untagged_resources:
        blocks.append(Heading("Largest untagged resources", 3))
        blocks.append(
            Table(["Resource", "Cost", "%"], [[s.name, usd(s.cost), _pct(s.pct)] for s in res.top_untagged_resources])
        )
    return blocks


def rightsizing_blocks(res: RightsizeResult) -> list[Block]:
    blocks: list[Block] = [
        Heading("Rightsizing recommendations"),
        Para(
            f"{len(res.recommendations)} recommendations, combined estimated monthly delta "
            f"{usd(res.total_monthly_delta)} (negative = saving; Graviton deltas are incremental "
            "to any downsize on the same instance, so the sum does not double count)."
        ),
    ]
    if res.recommendations:
        blocks.append(
            Table(
                ["Resource", "Owner", "Action", "Current", "Proposed", "Est. monthly delta", "Confidence", "Compat test"],
                [
                    [
                        r.resource_id,
                        r.owner or "-",
                        r.kind,
                        r.current,
                        r.proposed,
                        usd(r.monthly_delta),
                        r.confidence,
                        "yes" if r.requires_compat_testing else "-",
                    ]
                    for r in res.recommendations
                ],
            )
        )
        blocks.append(Heading("Rationale", 3))
        blocks.append(Bullets([f"`{r.resource_id}` ({r.kind}): {r.rationale}" for r in res.recommendations]))
        if any(r.requires_compat_testing for r in res.recommendations):
            caveat = next(r.caveat for r in res.recommendations if r.requires_compat_testing)
            blocks.append(Para(f"Graviton caveat: {caveat}."))
    if res.skipped:
        blocks.append(Heading("Skipped", 3))
        blocks.append(Bullets(res.skipped))
    return blocks


def commitments_blocks(res: CommitmentResult) -> list[Block]:
    rec = res.recommended
    return [
        Heading("Commitments (Savings Plans / RIs)"),
        Para(
            f"Eligible services: {', '.join(res.eligible_services)}. Current commitment coverage "
            f"{_pct(res.coverage_pct)} of eligible list-price spend ({usd(res.covered_list_cost)} "
            f"committed vs {usd(res.on_demand_list_cost)} on-demand) over {res.hours} hours."
        ),
        Para(
            f"Recommendation: commit ${rec.commitment_hourly}/h (covers ${rec.od_equivalent_hourly}/h of "
            f"on-demand usage, the {rec.label} of the hourly on-demand baseline) at an illustrative "
            f"{res.discount * 100:.0f}% discount -> projected utilisation {_pct(rec.utilization_pct)}, "
            f"estimated net saving {usd(rec.monthly_net_savings)}/month. Mean on-demand rate is "
            f"${res.mean_od_hourly}/h."
        ),
        Para(
            "Why a percentile of the baseline, not the mean: every hour below the commitment is paid "
            "for but unused. The sweep shows utilisation falling and net savings flattening or "
            "reversing as the commitment rises toward the mean and beyond. A marginal dollar of "
            "commitment only pays off if usage reaches it in more than (1 - discount) of hours, so on "
            f"this history levels above ~P{res.breakeven_percentile:.0f} (the discount rate) lose money; "
            "choosing a percentile at or below that leaves headroom for rightsizing and usage decline."
        ),
        Table(
            ["Level", "Covers OD $/h", "Commit $/h", "Utilisation", "Net monthly saving"],
            [
                [s.label, str(s.od_equivalent_hourly), str(s.commitment_hourly), _pct(s.utilization_pct),
                 usd(s.monthly_net_savings)]
                for s in res.sweep
            ],
        ),
    ]


def budget_blocks(res: BudgetResult) -> list[Block]:
    status = "BREACH" if res.breached else "OK"
    return [
        Heading("Budget"),
        Para(
            f"{res.month} budget {usd(res.budget)}: month-to-date {usd(res.month_to_date)} "
            f"({_pct(res.actual_pct)}) after {res.days_elapsed}/{res.days_in_month} days; "
            f"forecast month-end {usd(res.forecast_month_end)} ({_pct(res.forecast_pct)}). "
            f"Gate: {res.measure} >= {res.fail_at}% -> **{status}**."
        ),
        Table(
            ["Threshold", "Actual crossed", "Forecast crossed"],
            [
                [f"{t.threshold_pct}%", "yes" if t.actual_crossed else "no", "yes" if t.forecast_crossed else "no"]
                for t in res.thresholds
            ],
        ),
    ]


def forecast_blocks(res: ForecastResult, show_days: int = 7) -> list[Block]:
    f = res.fit
    preds = res.predictions
    return [
        Heading("Forecast"),
        Para(
            f"Linear fit over {res.lookback_days} days ({res.history_start} to {res.history_end}): "
            f"trend {usd(res.slope_per_day)}/day, R^2 {f.r_squared:.3f}, residual std "
            f"{usd(Decimal(str(round(f.residual_std, 2))))}. Next {len(preds)} days: {usd(res.total)}."
        ),
        Table(
            ["Day", "Forecast", "Low", "High"],
            [[str(p.day), usd(p.cost), usd(p.low), usd(p.high)] for p in preds[:show_days]],
        ),
        Para(
            "Limitations: no seasonality, step changes skew the slope until they age out of the "
            "lookback window, and the band is +/- one residual standard deviation, not a calibrated interval."
        ),
    ]


# --------------------------------------------------------------------------- renderers


def _md_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def to_markdown(blocks: Sequence[Block]) -> str:
    out: list[str] = []
    for b in blocks:
        if isinstance(b, Heading):
            out.append(f"{'#' * b.level} {b.text}\n")
        elif isinstance(b, Para):
            out.append(f"{b.text}\n")
        elif isinstance(b, Bullets):
            out.append("\n".join(f"- {i}" for i in b.items) + "\n")
        elif isinstance(b, Table):
            out.append("| " + " | ".join(_md_cell(h) for h in b.headers) + " |")
            out.append("|" + "|".join("---" for _ in b.headers) + "|")
            for row in b.rows:
                out.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def _plain(text: str) -> str:
    return text.replace("**", "").replace("`", "")


def to_text(blocks: Sequence[Block]) -> str:
    out: list[str] = []
    for b in blocks:
        if isinstance(b, Heading):
            t = _plain(b.text)
            out.append(f"\n{t}\n{('=' if b.level <= 2 else '-') * len(t)}")
        elif isinstance(b, Para):
            out.append(_plain(b.text))
        elif isinstance(b, Bullets):
            out.extend(f"  * {_plain(i)}" for i in b.items)
        elif isinstance(b, Table):
            rows = [list(b.headers)] + [list(r) for r in b.rows]
            widths = [max(len(str(r[i])) for r in rows) for i in range(len(b.headers))]
            for n, r in enumerate(rows):
                out.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)).rstrip())
                if n == 0:
                    out.append("  ".join("-" * w for w in widths))
    return "\n".join(out).strip() + "\n"


def _inline_html(text: str) -> str:
    escaped = html.escape(text)
    parts = escaped.split("**")
    escaped = "".join(f"<strong>{p}</strong>" if i % 2 else p for i, p in enumerate(parts))
    parts = escaped.split("`")
    return "".join(f"<code>{p}</code>" if i % 2 else p for i, p in enumerate(parts))


_CSS = """
:root{--bg:#fff;--fg:#1f2328;--muted:#59636e;--line:#d1d9e0;--head:#f6f8fa}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--line:#3d444d;--head:#151b23}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;
max-width:1100px;margin:0 auto;padding:24px 16px}
h1{font-size:1.6rem}h2{border-bottom:1px solid var(--line);padding-bottom:4px;margin-top:2rem}
.note{color:var(--muted);border-left:3px solid var(--line);padding-left:10px}
.scroll{overflow-x:auto}table{border-collapse:collapse;margin:8px 0 16px;font-size:13px}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;white-space:nowrap}
th{background:var(--head)}code{font-size:12px}
"""


def to_html(blocks: Sequence[Block], title: str) -> str:
    body: list[str] = []
    for b in blocks:
        if isinstance(b, Heading):
            body.append(f"<h{b.level}>{_inline_html(b.text)}</h{b.level}>")
        elif isinstance(b, Para):
            cls = ' class="note"' if b.text == DISCLAIMER else ""
            body.append(f"<p{cls}>{_inline_html(b.text)}</p>")
        elif isinstance(b, Bullets):
            body.append("<ul>" + "".join(f"<li>{_inline_html(i)}</li>" for i in b.items) + "</ul>")
        elif isinstance(b, Table):
            head = "".join(f"<th>{html.escape(str(h))}</th>" for h in b.headers)
            rows = "".join(
                "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in b.rows
            )
            body.append(f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )


# --------------------------------------------------------------------------- full report


def build_report(
    allocation: AllocationResult,
    rightsizing: RightsizeResult,
    commitments: CommitmentResult,
    forecast: ForecastResult,
    budget: BudgetResult | None,
) -> list[Block]:
    savings = rightsizing.total_monthly_delta
    summary = [
        f"Total spend analysed: {usd(allocation.total)} ({allocation.cost_column} cost); "
        f"{_pct(allocation.no_tags_at_all.pct)} carries no allocation tags.",
        f"Rightsizing: {len(rightsizing.recommendations)} recommendations, estimated monthly delta "
        f"{usd(savings)} (negative = saving).",
        f"Commitments: coverage {_pct(commitments.coverage_pct)}; recommended additional "
        f"${commitments.recommended.commitment_hourly}/h -> est. "
        f"{usd(commitments.recommended.monthly_net_savings)}/month net.",
        f"Forecast: {usd(forecast.total)} over the next {len(forecast.predictions)} days "
        f"(trend {usd(forecast.slope_per_day)}/day).",
    ]
    if budget is not None:
        summary.append(
            f"Budget {budget.month}: forecast {_pct(budget.forecast_pct)} of {usd(budget.budget)} -> "
            f"{'BREACH' if budget.breached else 'OK'}."
        )
    blocks: list[Block] = [
        Heading("FinOps cost report", 1),
        Para(DISCLAIMER),
        Heading("Summary"),
        Bullets(summary),
    ]
    blocks += allocation_blocks(allocation)
    blocks += rightsizing_blocks(rightsizing)
    blocks += commitments_blocks(commitments)
    blocks += forecast_blocks(forecast)
    if budget is not None:
        blocks += budget_blocks(budget)
    return blocks


def write_report(
    out_dir: Path | str,
    blocks: Sequence[Block],
    summary: dict,
    html_output: bool = False,
) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = [out / "report.md", out / "summary.json"]
    written[0].write_text(to_markdown(blocks), encoding="utf-8")
    written[1].write_text(json.dumps(to_jsonable(summary), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if html_output:
        path = out / "report.html"
        path.write_text(to_html(blocks, "FinOps cost report"), encoding="utf-8")
        written.append(path)
    return written
