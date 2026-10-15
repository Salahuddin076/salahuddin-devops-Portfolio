# Runbook: orders-worker freshness, slow burn (ticket)

**Alerts:** `OrdersWorkerFreshnessBurnTicket1d` (3x over 1d and 2h),
`OrdersWorkerFreshnessBurnTicket3d` (1x over 3d and 6h). **Severity:** ticket.
**SLO:** 99.5% of orders processed within 5 minutes, over 28 days.

## What it means

A steady fraction of orders (above 0.5% at 1x, above 1.5% at 3x) takes longer
than 5 minutes. Usually a capacity or scheduling problem rather than an outage.

## Within one working day

1. When are orders late? Plot the late fraction by hour:
   `1 - sum(rate(orders_processing_lag_seconds_bucket{le="300.0"}[1h])) / sum(rate(orders_processing_lag_seconds_count[1h]))`
   Peaks at the same hour each day point at capacity at peak or a batch job.
2. Check the autoscaler: does it react fast enough (polling interval,
   cooldown), and is max replicas reached at peak?
3. Check retries: messages that fail and retry later count as late.
4. Open a ticket for `team=fulfilment` with the hourly pattern.

## Close-out

Capacity fixes (higher max, faster scale-up) go through the usual change
process. Review at the weekly SLO meeting if the budget is below 25%.
