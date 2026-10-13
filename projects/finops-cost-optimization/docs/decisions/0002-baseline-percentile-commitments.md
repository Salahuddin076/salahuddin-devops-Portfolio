# ADR 0002: Size commitments from a percentile of the hourly on-demand baseline

- Status: Accepted
- Date: 2026-10-14

## Context

Savings Plans and Reserved Instances trade a fixed hourly commitment for a
discount `d` on usage up to that commitment. The commitment is paid every
hour whether or not usage reaches it. Usage varies hour to hour (business-hours
batch, weekend scale-in, autoscaling), and a commitment lasts 1 or 3 years
while the estate keeps changing (rightsizing, Graviton migration,
decommissioning).

The tempting heuristic is to commit to average spend.

## Decision

Recommend a commitment equal to a configurable **low percentile (default
P20)** of the hourly **on-demand** eligible spend that remains after existing
commitments, multiplied by `(1 - d)` to express it as the $/hour you actually
commit. Also show a sweep (P0, P10, P20, P30, P50, P75 and the mean) with
utilisation and net monthly savings for each level, so the trade-off can be
seen.

## Rationale

Consider one more dollar per hour of commitment at level `c`:

- it costs `(1 - d)` every hour
- it saves `1` only in hours where usage is at least `c`

So it pays off only if usage is at or above `c` in more than `(1 - d)` of
hours. Equivalently, `c` must be at or below the `d`-th percentile of the hourly
distribution. With a 28% discount, any level above roughly P28 loses money
on historical data. The mean sits well above that whenever usage has a
long tail of peaks, so committing to it means paying for unused commitment
in a large share of hours.

We default to a percentile **below** the break-even point because:

1. History overstates future usage. Rightsizing and Graviton work, often
   recommended by the same report, lowers the baseline after you commit.
2. Under-committing costs only part of the discount on the gap, because that
   usage stays at on-demand price. Over-committing pays for capacity that
   isn't used, for the rest of the term.
3. Commitments can be layered: buy at P20 now and add more after the next
   review, which is cheaper than being stuck with an oversized plan.

## Consequences

- Recommendations are conservative. The sweep makes the money left on the
  table visible, and the percentile is a CLI flag (`--percentile`).
- Rightsize first, then commit. The report puts both in one document for that
  reason.
- Daily-granularity exports are spread evenly across 24 hours, which hides
  intra-day peaks and makes the baseline look flatter than it is. Use hourly
  exports for real purchases.
- The discount is an illustrative input (`--discount`), not a quoted rate.
  Actual Savings Plans rates vary by term, payment option, family and region.
- Coverage of existing commitments uses `ListCost`, the on-demand equivalent,
  so covered and uncovered usage are compared on the same basis.
