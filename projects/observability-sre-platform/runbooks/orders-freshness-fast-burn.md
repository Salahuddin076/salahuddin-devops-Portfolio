# Runbook: orders-worker freshness, fast burn (page)

**Alerts:** `OrdersWorkerFreshnessBurnPage1h` (14.4x over 1h and 5m),
`OrdersWorkerFreshnessBurnPage6h` (6x over 6h and 30m). **Severity:** page.
**SLO:** 99.5% of orders are processed within 5 minutes of being enqueued,
over 28 days (budget 0.5%). 14.4x means more than 7.2% of orders are late.

## What it means

Orders are piling up or being processed slowly. Customers don't see an error,
but fulfilment is delayed. Note: if the worker is completely stopped, no
orders are *processed*, so the lag histogram stops growing and the ratio can
go empty instead of high. Check the queue depth, not just this alert.

## First five minutes

1. Queue depth and age of the oldest message (from the broker exporter).
2. Worker replicas and restarts:
   `kube_deployment_status_replicas_available{deployment="orders-worker"}`
3. Processing errors in the worker logs (Loki: `{service="orders-worker"} |= "error"`).
4. Downstream: fulfilment API latency and errors.

## Common causes

| Signal | Cause | Action |
|---|---|---|
| queue growing, workers at max | traffic spike | raise max replicas / concurrency |
| queue growing, workers crash-looping | bad release or poison message | roll back; move the poison message to the DLQ |
| processing slow, downstream slow | fulfilment API degraded | back off, page that team |
| workers at 0 | autoscaler or credentials broken | check the scaler and the queue credentials |

## After

Late orders may need a manual check that nothing was dropped. Record the
budget spent in the incident doc.
