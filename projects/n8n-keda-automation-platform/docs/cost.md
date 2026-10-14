# Cost (illustrative)

**Every figure here is illustrative**: rounded on-demand list prices for
us-east-1 as I understand them, not a quote and not anyone's bill. Check the
AWS pricing pages for your region and date. The *shape* of the comparison is
the point, not the numbers.

## What scales and what doesn't

| Part | Scales with load? | Illustrative monthly |
|---|---|---|
| RDS PostgreSQL db.t4g.medium, Multi-AZ, 50 GiB gp3 | no: fixed floor | ~$100-110 (instance ~$95 Multi-AZ, storage ~$12) |
| ElastiCache Valkey cache.t4g.small x2 (Multi-AZ) | no: fixed floor | ~$45-50 |
| Secrets Manager, 3 secrets + KMS key | no | ~$2 + $1 |
| main pod (0.5 vCPU / 1 GiB requested) | no | share of a node, ~$15 |
| webhook pods, 3 always on (prod min) | slowly (HPA on CPU) | ~$25-35 |
| worker pods (1 vCPU / 1.5 GiB requested each) | yes, to zero (KEDA) | see below |
| ALB | per LCU | ~$20 + traffic |

The fixed floor (RDS + Valkey + ALB + the always-on pods) is roughly
**$200-230 a month** before any workflow runs. Scale-to-zero only touches the
worker line, so it pays off when workers are a large share of the bill: many
workers at peak, long idle periods.

## Workers at zero vs always-on

Worker capacity cost, assuming a worker is about a quarter of an m7g.large
(2 vCPU, 8 GiB, ~$0.082/h), so ~$0.02 per worker-hour, and that the cluster
autoscaler (Karpenter or similar) actually removes the freed nodes:

| Pattern | Worker-hours / month | Illustrative |
|---|---|---|
| Always-on at the prod max (30 workers x 730 h) | 21,900 | ~$440 |
| Always-on at a "typical" 10 workers | 7,300 | ~$146 |
| KEDA, business-hours bursts: ~10 workers for 3 h a day, 22 days, zero otherwise | ~660 | ~$13 |

The simulator gives the same ratio for a given queue shape. On the sample
(two bursts in 30 minutes), the chart's default settings use 6,420
worker-seconds against 18,010 for 10 always-on workers: **35.6%**. Most of
what remains is the cooldown and stabilization tail, about 5 minutes of
workers after each burst, which is the price of not flapping.

```bash
python3 scripts/keda_scaling_sim.py sample-data/queue-depth.csv --values helm/n8n-platform/values.yaml
# summary: peak 10 replicas, 15 scaling events, 2 scale-to-zero, 6420 worker-seconds vs 18010 at max always-on (35.6%)
```

## Where the savings go

- **The tail is a dial.** `cooldownPeriod` and the scale-down stabilization
  window decide how long idle workers live after a burst. Halving both roughly
  halves the tail, but a gap shorter than the cooldown then costs a cold start
  (tens of seconds of image pull, CSI mount and n8n boot) instead.
- **Nodes, not pods, are the bill.** Workers at zero save money only if their
  nodes go away. With a fixed node group, scale-to-zero frees capacity for
  other workloads but doesn't shrink the invoice.
- **The fixed floor dominates small installs.** At a few hundred executions a
  day, RDS and Valkey are most of the cost. Cheaper levers there: single-AZ
  Valkey for non-prod (`cache_multi_az = false`), a smaller RDS class, and
  execution-data pruning (`EXECUTIONS_DATA_MAX_AGE`) to keep storage flat.
- **Aurora Serverless v2 doesn't remove the floor here.** main holds DB
  connections open permanently, so the cluster never pauses
  ([ADR 0004](decisions/0004-database-choice.md)).
