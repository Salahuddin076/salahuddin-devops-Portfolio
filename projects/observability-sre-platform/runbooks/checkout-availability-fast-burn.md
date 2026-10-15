# Runbook: checkout-api availability, fast burn (page)

**Alerts:** `CheckoutApiAvailabilityBurnPage1h` (14.4x over 1h and 5m),
`CheckoutApiAvailabilityBurnPage6h` (6x over 6h and 30m). **Severity:** page.
**SLO:** 99.9% of checkout requests are not 5xx over 30 days (budget 0.1%).

## What it means

At 14.4x, 2% of the month's error budget goes every hour and the whole budget
is gone in about 2 days. At 6x, 5% goes every 6 hours (empty in 5 days). The
short window means it is happening now, not just that it happened earlier.
Customers are failing to check out. Treat it as an incident
([incident-response.md](incident-response.md)).

## First five minutes

1. Acknowledge the page and open the **SLO / checkout-api** dashboard. Check
   the burn-rate panel: is the 5m line still above 14.4x, or falling?
2. Check the error ratio by route and status code:
   `sum by (route, code) (rate(http_requests_total{job="checkout-api",code=~"5.."}[5m]))`
3. Did anything change? Deploys, feature flags, config, the payment
   provider's status page, database failovers in the last hour.
4. If a deploy lines up with the start: **roll back first**, investigate after.

## Common causes

| Signal | Likely cause | Action |
|---|---|---|
| 5xx started at a deploy | bad release | roll back |
| 503 / upstream timeouts on payment calls | payment provider degraded | enable the provider fallback, post on the status page |
| 500s with DB errors in logs (Loki: `{service="checkout-api"} \|= "db"`) | connection pool exhausted or DB failover | check DB health, scale pool or the API |
| all pods restarting | OOM or a failing dependency in the readiness probe | check `kube_pod_container_status_restarts_total` |

## Mitigate, then resolve

- The page resolves itself when the 5m (or 30m) ratio drops below the
  threshold. Don't silence it while customers are still failing.
- After mitigation, the ticket alerts for this SLO may stay active for hours;
  they are inhibited while the page fires and should be reviewed in the
  postmortem, not chased.
- Record the budget spent (dashboard: *Error budget remaining*) in the
  incident doc. If it drops below zero, the [error-budget policy](error-budget-policy.md)
  applies.
