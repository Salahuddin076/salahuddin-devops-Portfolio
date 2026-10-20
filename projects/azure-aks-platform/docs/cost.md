# Cost

All figures below are illustrative order-of-magnitude placeholders for `eastus2` list pricing at the time this reference was written. They are not sourced from a real bill -- nothing here has ever been deployed -- and should never be quoted as a committed estimate.

| Component | Shape | Illustrative monthly cost |
|---|---|---|
| AKS control plane | `Standard` tier (uptime SLA) | ~$75 flat |
| Azure Firewall | `Standard` SKU, 1 shared instance + ~100GB/day processed | ~$950 (fixed + throughput) |
| Azure Bastion | `Standard` SKU | ~$140 |
| System node pool | 3x `Standard_D4s_v5`, on-demand, always on, 3 zones | ~$440 |
| User node pool | 2x `Standard_D4s_v5`, on-demand | ~$290 |
| Spot node pool | `Standard_D4s_v5`, spot, autoscales 0-10, assume ~10% average utilization | ~$60 average, significant spike at a sustained full burst |
| Container Registry | Premium SKU (required for private endpoints) | ~$50 |
| Key Vault + private endpoints (x2) | Standard tier, low operation volume | ~$15 |
| Log Analytics | Default retention, `kube-audit` + `AllMetrics` diagnostic categories | ~$30-80, scales with audit log volume |

## What actually drives cost here

- **Azure Firewall is the single largest fixed line item**, by a wide margin -- larger than the cluster's compute in this reference's sizing. That's the point of making it a shared hub resource: a second, third, or tenth spoke peers to the same hub and the same firewall instead of each paying its own ~$950/month fixed cost. The website's project page calls this out explicitly ("share one hub across spokes"); see `terraform/modules/hub`, which has no spoke-count parameter because it's designed to be created once.
- **Spot pricing + scale-to-zero is the lever on the interruptible pool**, the same pattern used for the AI pool in `gcp-ai-pharmacy-platform`: a `min_count = 0` pool that only ever runs retryable, interruption-tolerant batch work costs nothing when idle, and the `priority = "Spot"` discount (typically 60-90% off on-demand) applies whenever it does scale up.
- **Bastion and three Availability Zones on every node pool are reliability choices with a real cost**, not free: Bastion is a flat ~$140/month regardless of how often it's used, and the `Standard_D4s_v5` always-on system/user pools are priced at full on-demand rate across all three zones rather than a cheaper single-zone layout. Both are deliberate trade-offs documented in `docs/architecture.md`, not oversights.
