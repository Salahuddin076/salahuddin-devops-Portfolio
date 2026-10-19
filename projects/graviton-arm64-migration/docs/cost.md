# Cost

**Illustrative.** These are us-east-1 on-demand list prices as published at
the time of writing; check the EC2 pricing page before quoting them. Nothing
here was measured against a real workload — these are the published price
deltas and a worked example, not a benchmark.

## The headline number

| Family | vCPU | Memory | On-demand (us-east-1) |
|---|---|---|---|
| m6i.large (x86) | 2 | 8 GiB | $0.0960 / hr |
| m7g.large (Graviton3) | 2 | 8 GiB | $0.0816 / hr |
| c6i.large (x86) | 2 | 4 GiB | $0.0850 / hr |
| c7g.large (Graviton3) | 2 | 4 GiB | $0.0725 / hr |

Graviton list price is roughly **15% lower** than the matching Intel/AMD
instance at the same vCPU/memory size, before any workload-specific
throughput difference. AWS publishes a wider range (up to ~40% better
price-performance) for workloads that also run meaningfully faster per vCPU
on Graviton — that number depends on the workload and isn't assumed here.

## A worked example: one node group, two architectures

`terraform/examples/mixed-fleet` sizes a 3-node x86 pool (`m6i.large`,
on-demand) and a 2-node Graviton pool (`m7g.large`, Spot — see below).

| Pool | Instances | Pricing | Monthly (730 hrs) |
|---|---|---|---|
| x86-stable (m6i.large × 3, on-demand) | 3 | $0.0960/hr | **$210.24** |
| graviton-migration (m7g.large × 2, Spot, ~70% off illustrative) | 2 | ~$0.0245/hr | **$35.77** |

If the same 2 Graviton nodes ran on-demand instead of Spot: 2 ×
$0.0816/hr × 730 = **$119.14/month**, still about 15% under the equivalent
on-demand x86 capacity ($140.16 for 2 × m6i.large).

Both pools exist simultaneously during a migration, so the cost during
migration is **additive**, not a swap — the savings only show up after the
x86 pool is scaled down in the `complete` rollout stage (see
[operations.md](operations.md)). A migration that never finishes scaling
down the old pool keeps paying for both.

## Spot for the Graviton pool

`terraform/modules/eks-arch-node-group`'s `capacity_type` variable defaults
to `ON_DEMAND` (the safer choice while a pool is still under compatibility
testing) but the mixed-fleet example sets the Graviton pool to `SPOT`. Once
a service has passed compatibility testing and reached the `partial` or
`complete` rollout stage, Spot + Graviton is a common pairing in practice:
Spot interruption risk is usually lower for a less commonly requested
instance family, and the PodDisruptionBudget in `helm/multiarch-app` keeps
the service available through node churn either way.

## ECR

Storage is $0.10/GB-month regardless of architecture; a multi-arch manifest
list roughly doubles image storage per tag (two platform layers instead of
one), which is the direct cost of multi-arch at the registry. Enhanced
(continuous) scanning, if turned on during an active migration
(`enhanced_scanning = true`), is priced per image scanned per month — turn
it off once both platforms have a steady `pass` and the service reaches
`complete`.

## What this doesn't include

- Data transfer, EBS, and the EKS control plane fee are identical regardless
  of node architecture and aren't broken out here.
- No throughput/price-performance benchmark is included — only the sticker
  price delta. A workload that runs meaningfully faster per vCPU on
  Graviton3 changes the real comparison; that's exactly what the canary
  stage in [operations.md](operations.md) is for.
