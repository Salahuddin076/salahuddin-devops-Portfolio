# ADR 0001: Multi-window, multi-burn-rate SLO alerts

**Status:** accepted

## Context

We want to page when an SLO is at real risk and stay quiet otherwise. The
simple options each fail one way:

- **Threshold on the error ratio** (e.g. > 0.1% over 5m): pages on every blip;
  most pages spend a negligible part of the budget.
- **Long window only** (e.g. budget burn over 1d): catches slow burns but
  detects a full outage late, and keeps firing for hours after the fix.
- **Single burn rate, single window**: a trade-off between precision and
  detection time that is wrong for either fast or slow problems.

## Decision

Use the Google SRE workbook's multi-window, multi-burn-rate alerts. Four tiers:

| Tier | Severity | Burn | Long | Short | Budget spent when it fires (30d) |
|---|---|---|---|---|---|
| page-1h | page | 14.4x | 1h | 5m | 2% |
| page-6h | page | 6x | 6h | 30m | 5% |
| ticket-1d | ticket | 3x | 1d | 2h | 10% |
| ticket-3d | ticket | 1x | 3d | 6h | 10% |

An alert requires the burn over **both** windows. The long window sets the
significance (how much budget is at stake), the short window (1/12 of the
long one) makes the alert stop soon after the problem does. Budget spent in
the long window = burn rate x long window / SLO window.

Each tier is its own alert, labelled with `severity`, `tier`, `burn_rate` and
the windows, so the receiver knows which condition fired. Tickets are
inhibited while a page for the same SLO fires.

`for:` is 2m on pages (one or two bad scrapes don't page) and 15m on tickets.
The workbook uses no `for:`; a short one is a small, deliberate addition.

## Consequences

- 7 recording rules per SLO (5m, 30m, 1h, 2h, 6h, 1d, 3d) so alert
  expressions stay cheap and readable.
- The 1d and 3d windows are expensive to evaluate on high-cardinality SLIs
  (docs/cost.md).
- Low-traffic services make short windows noisy; that needs per-SLO tuning
  (docs/operations.md), which the tier list per SLO allows. The public website
  already drops `page-6h`.
- Verified with promtool unit tests: the short window resets a page while the
  1h ratio is still above threshold, and a 2x latency burn opens only the 1x ticket.
