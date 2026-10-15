# Runbook: checkout-api latency, slow burn (ticket)

**Alerts:** `CheckoutApiLatencyBurnTicket1d` (3x over 1d and 2h),
`CheckoutApiLatencyBurnTicket3d` (1x over 3d and 6h). **Severity:** ticket.
**SLO:** 99% of checkout requests in 300 ms or less over 28 days.

## What it means

Between 1% and 3% (1x) or above 3% (3x) of requests have been slower than
300 ms for a day or more. At 1x the budget lasts exactly the 28-day window.

## Within one working day

1. Compare p99 latency by route this week vs last week:
   `histogram_quantile(0.99, sum by (le, route) (rate(http_request_duration_seconds_bucket{job="checkout-api"}[1d])))`
2. Look for gradual causes: growing tables without an index, a payload that
   got bigger, a dependency that slowed down, a noisy neighbour on shared nodes.
3. Use traces (Tempo) to find the slow span for requests over 300 ms.
4. Open a performance ticket for `team=payments` with the evidence.

## Close-out

If 300 ms is no longer the right target for customers, change the SLO through
review (docs/operations.md, "Adding or changing an SLO"), not by editing the
generated rules.
