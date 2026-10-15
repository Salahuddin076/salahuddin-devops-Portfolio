# Runbook: checkout-api availability, slow burn (ticket)

**Alerts:** `CheckoutApiAvailabilityBurnTicket1d` (3x over 1d and 2h),
`CheckoutApiAvailabilityBurnTicket3d` (1x over 3d and 6h). **Severity:** ticket.
**SLO:** 99.9% of checkout requests are not 5xx over 30 days.

## What it means

Errors are elevated but not urgent: at 3x the budget lasts 10 days, at 1x it
lasts exactly the 30-day window. Nobody is paged. Left alone, this SLO will
be missed this month. Inhibited while a page for the same SLO is firing.

## Within one working day

1. Open the **SLO / checkout-api** dashboard and find when the 1d / 3d burn
   lines crossed 3x / 1x.
2. Find the error source:
   `topk(5, sum by (route, code) (increase(http_requests_total{job="checkout-api",code=~"5.."}[1d])))`
3. Typical slow burns: one route failing for a subset of customers, a retry
   storm from one client, a dependency with a rising timeout rate, a release
   that added a rare 500 path.
4. Open a bug with the owner team (label `team=payments`) and link this alert.

## Close-out

- Fix or accept: if the errors are expected (a client sending invalid input
  that we answer with 500 instead of 4xx), fix the status code, not the SLO.
- If the budget is below 25%, raise it at the weekly SLO review
  ([error-budget-policy.md](error-budget-policy.md)).
