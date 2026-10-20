# Cost

All figures below are illustrative order-of-magnitude placeholders for `us-central1` list pricing at the time this reference was written. They are not sourced from a real bill — nothing here has ever been deployed — and should never be quoted as a committed estimate.

| Component | Shape | Illustrative monthly cost |
|---|---|---|
| GKE control plane | Regional (standard tier) | ~$75 flat |
| API node pool | 2× `e2-standard-4`, on-demand, always on | ~$140 |
| AI node pool | `n2-highmem-8`, spot, autoscales 0–10, assume ~10% average utilization | ~$90 average, ~$900 at a sustained full burst |
| Cloud SQL | `db-custom-2-8192`, `REGIONAL` (HA) | ~$250 |
| Secret Manager | A handful of secrets, low access volume | <$5 |
| Artifact Registry | Image storage, a few GB | <$5 |
| Cloud Build | A few dozen builds/month, default machine type | ~$10–20 |
| Cloud Logging | Default retention, audit logs on for two services | ~$20–50, scales with `DATA_READ` volume |
| Cloud Monitoring (Managed Prometheus) | Default metrics | ~$10–30 |

## What actually drives cost here

- **The AI pool's spot pricing + scale-to-zero is the single biggest lever.** An AI pool kept warm at `min_count` equal to its peak-hour node count, on-demand, would cost roughly 3–5x the "average" line above. Scaling to zero outside working hours, and using spot for a workload that's inherently retryable (inference requests, not a stateful service), is what keeps the illustrative average low.
- **`DATA_READ` audit logging on Cloud SQL** is the audit requirement with the most real cost exposure: at high query volume it can dominate the logging line. The requirement itself isn't optional for this data classification, but it's worth sizing with actual query volume, not just enabled by default and forgotten.
- **Cloud SQL HA roughly doubles compute cost** versus a single-zone instance of the same tier, since the standby replica runs continuously. That trade is the explicit reliability choice documented in `docs/decisions/0003-cloud-sql-ha-by-default.md`.
