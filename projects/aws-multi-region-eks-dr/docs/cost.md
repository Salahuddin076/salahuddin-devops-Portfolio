# Cost

> **Illustrative and approximate.** These are rough us-east-1 / us-west-2
> on-demand list prices, rounded, at 730 hours a month, with no discounts
> or Savings Plans. They are not a quote and were not taken from a bill.
> Prices change: use the AWS Pricing Calculator with your own sizes before
> deciding anything.

## What the warm standby costs

The question a warm standby has to answer is what you pay every month for
a region that serves no customer traffic. In this design the answer is
mostly four things.

| Item (DR region) | Sizing in this repo | Approx. USD/month | Notes |
|---|---|---|---|
| Aurora secondary cluster | 1 x db.r7g.large | ~200 | Same class as the primary, so it can take the full load after promotion. Plus replicated storage at the normal per-GB rate |
| Aurora Global Database replicated writes | per million write I/Os replicated | ~20-100 | Scales with write volume; the least predictable line |
| EKS control plane | 1 cluster, standard support | ~73 | Fixed. Extended support costs 6x, which is why `upgrade_policy` pins STANDARD |
| Nodes | 2 x m7g.large | ~120 | `node_scaling` min/desired 2, max 12 for failover |
| NAT gateway | 1 (single, `nat_gateway_per_az = false`) | ~33 + data | The primary runs 3 |
| ALB | 1, idle except for health checks | ~20 | Created by the controller |
| Valkey | 1 x cache.t4g.small | ~25 | One node: losing it only costs a cold cache ([ADR 0003](decisions/0003-valkey-rebuildable.md)) |
| Route 53 health checks | 2 HTTPS checks at 30 s | ~2 | 10 s intervals cost more |
| Cross-region transfer | Aurora replication, S3 CRR | ~0.02/GB | Scales with change rate, not with size |
| S3 replica storage | same as the primary bucket | per GB | Plus RTC per GB if enabled |
| **Rough standby floor** | | **~500-600 + transfer** | |

For comparison, the primary region at these sizes (2 Aurora instances, 3
NATs, 3+ nodes, 2 Valkey nodes) is roughly 1,000-1,300 USD a month before
traffic-driven costs. The standby runs at very roughly 40-50% of the
primary's fixed cost. Both figures are fixed costs only: traffic-driven
costs are excluded (see the last section).

## Levers, and what each one costs you

| Lever | Saves | Costs |
|---|---|---|
| Headless Aurora secondary (no instance) | ~200/month | Promotion first has to create an instance: minutes added to recovery. Disallowed here by `dr_instance_count >= 1` |
| Smaller DR Aurora instance | ~half of that line | Under-sized writer right after failover, while the cache is cold and load is highest |
| Pilot light: API at 0, 1 node | ~100/month | No continuous proof that the DR path works; Route 53 can't health-check a region with nothing running |
| Interface endpoints instead of NAT | NAT data charges | ~7/month per endpoint per AZ; worth it with heavy AWS API traffic |
| S3 RTC off (default) | per-GB RTC fee | No 15-minute replication SLA or replication metrics |
| On-Demand Capacity Reservations for failover size | negative: adds cost | Guarantees the capacity to scale up during a regional event |

## Costs during a failover

While DR is active, it runs at primary size (the scale step raises the HPA
minimum and enables workers, and the node group grows), and the old
primary keeps its fixed costs until it is rebuilt or scaled down. For the
length of the incident, expect roughly 1.5-2x the normal fixed bill.

## What this does not include

Traffic-driven costs (ALB LCUs, NAT data processing, egress to the
internet), CloudWatch logs and metrics, KMS requests, Secrets Manager API
calls, ECR replication storage, backups (see the sibling
[aws-backup-cross-region-dr](../../aws-backup-cross-region-dr/) project),
support plans and taxes.
