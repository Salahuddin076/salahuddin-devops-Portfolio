# Cost

**Illustrative.** These are us-east-1 list prices as published at the time of writing.
Check the Secrets Manager and KMS pricing pages before quoting them. The EKS add-on, the
CSI driver and Pod Identity have no charge of their own; they run on nodes you already pay
for.

| Item | Unit price | This stack |
|---|---|---|
| Secrets Manager secret | $0.40 per secret per month | 2 secrets → **$0.80 / month** |
| Secrets Manager API calls | $0.05 per 10,000 calls | depends on pods × secrets × poll interval (below) |
| KMS customer-managed key | $1.00 per key per month | 1 key → **$1.00 / month** |
| KMS requests | $0.03 per 10,000 requests | assume one `Decrypt` per `GetSecretValue` (worst case) |
| Rotation Lambda (optional) | Lambda pricing; a few invocations per rotation | negligible |

## What drives API calls

With rotation enabled, the driver re-fetches **every mounted secret, for every pod, every
`rotationPollInterval`**, whether or not anything changed. jmesPath doesn't add calls: one
`GetSecretValue` yields all three DB files. Mount-time fetches (one per secret per pod start)
are small next to polling.

```text
calls/month ≈ pods × secrets × (2,592,000 s / rotationPollInterval in seconds)
```

| Pods | Secrets | Poll interval | Calls / month | Secrets Manager calls | KMS requests (worst case) |
|---|---|---|---|---|---|
| 2 | 2 | 2m (default) | 86,400 | $0.43 | $0.26 |
| 20 | 2 | 2m | 864,000 | $4.32 | $2.59 |
| 50 | 2 | 2m | 2,160,000 | $10.80 | $6.48 |
| 50 | 2 | 30s (module minimum) | 8,640,000 | $43.20 | $25.92 |
| 50 | 2 | 10m | 432,000 | $2.16 | $1.30 |

So for this two-secret app the fixed part ($1.80 / month) dominates until a few dozen pods.
After that, cost scales linearly with replicas and inversely with the interval.

## Choosing the interval

- **Pickup latency** is `rotationPollInterval + SECRETS_POLL_SECONDS`
  ([architecture](architecture.md#rotation-without-a-restart)). With alternating-users DB
  rotation, the old credential stays valid for a whole rotation cycle (days). A 2-10 minute
  pickup is fine, and 30 s buys nothing but calls.
- **Throttling matters before cost does.** `GetSecretValue` has a per-account, per-region
  request quota (thousands per second; check Service Quotas). A large cluster with a short
  interval and many secrets per pod can approach it, and a node drain that restarts many
  pods at once spikes mount-time calls. Longer intervals and fewer, bundled secrets (one JSON
  document split with jmesPath, as here) keep you far from it.
- **The app's own poll is free.** `SECRETS_POLL_SECONDS` is a local `stat()` on tmpfs, so 10 s
  costs nothing.
- **If rotation is off**, calls drop to mount time only. The trade-off is that a rotated
  value reaches pods only when they restart.

## Compared with the alternatives

- **Synced Kubernetes Secrets** (`secretObjects`) add no AWS cost, but they add etcd copies
  ([ADR 0003](decisions/0003-files-not-env-vars.md)).
- **External Secrets Operator** polls once per `ExternalSecret` per `refreshInterval`, not
  per pod. That's cheaper at high replica counts, but values always land in etcd
  ([ADR 0001](decisions/0001-csi-driver-vs-external-secrets-operator.md)).
- **SSM Parameter Store standard parameters** have no per-parameter fee, but no managed
  rotation and a lower throughput tier. ASCP supports both (`objectType: ssmparameter`).
