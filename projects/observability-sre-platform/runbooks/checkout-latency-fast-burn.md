# Runbook: checkout-api latency, fast burn (page)

**Alerts:** `CheckoutApiLatencyBurnPage1h` (14.4x over 1h and 5m),
`CheckoutApiLatencyBurnPage6h` (6x over 6h and 30m). **Severity:** page.
**SLO:** 99% of checkout requests complete in 300 ms or less over 28 days
(budget 1%). 14.4x means more than 14.4% of requests are slower than 300 ms.

## First five minutes

1. Open **SLO / checkout-api**, latency row. Confirm the 5m burn is still high.
2. Latency by route:
   `histogram_quantile(0.99, sum by (le, route) (rate(http_request_duration_seconds_bucket{job="checkout-api"}[5m])))`
3. Saturation: CPU throttling
   (`rate(container_cpu_cfs_throttled_periods_total[5m])`), pod count vs HPA
   max, DB query latency, payment provider latency (traces in Tempo, filter
   `service.name=checkout-api` and `duration > 300ms`).
4. Recent deploy or traffic spike? Roll back a deploy; scale out for traffic.

## Common causes

- HPA at max replicas or CPU limits throttling: raise max / limits.
- A slow downstream (payment, inventory): check its own SLO dashboard;
  enable timeouts and the fallback path.
- Cold caches after a deploy or a cache cluster restart.
- GC pauses after a memory-heavy release.

## Notes

Latency budget burn rarely comes alone: check the availability SLO too, since
timeouts turn into 5xx. Record the budget spent in the incident doc.
