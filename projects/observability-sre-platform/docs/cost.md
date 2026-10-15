# Cost

**Illustrative only.** No figures here come from a real bill or a real
environment. Prices change; check the provider's current pricing page.

## What drives cost

| Driver | Why | Lever |
|---|---|---|
| Active series (cardinality) | memory and storage scale with series, not samples | drop high-cardinality labels (user IDs, full URLs, pod-hash on business metrics) at the source or with `metric_relabel_configs` |
| Samples per second | scrape interval x series | 30s instead of 15s halves it; SLO math doesn't need 15s |
| Retention | storage | short local retention (15d) + long-term storage only for recording rules |
| Rule evaluation | long-range rules read a lot of data | see below |
| Log volume | ingestion and storage per GB | drop debug logs in production, sample access logs, never log request bodies |
| Trace volume | spans per second | tail sampling in the Collector: keep errors and slow traces, sample the rest |

## SLO rules specifically

Per SLO: 7 windowed ratios + 4 meta rules = 11 recording rules, each producing
one series. Four SLOs = 44 series: trivial for storage. The cost is in
**evaluation**: `rate(...[3d])` re-reads three days of raw samples for every
underlying series on every evaluation. For a service with 500 raw series at a
15s scrape, the 3d window reads about 500 x 17,280 = 8.6 million samples per
evaluation.

Options when that becomes noticeable:

- Evaluate the long-window group less often (`interval: 5m` on the group; the
  1d/3d windows don't need 15-second freshness).
- Compute long windows from the short recording rule
  (`avg_over_time(slo:sli_error:ratio_rate5m[3d])`, as the period ratio
  already does). Much cheaper, but unweighted by traffic.
- Pre-aggregate `good` and `total` into recording rules first, then take
  ratios of those (`sum_over_time` of 5m increases).

## Self-hosted vs managed

Self-hosted (Prometheus + Loki + Tempo + Grafana on Kubernetes) costs nodes,
disks and object storage, plus the engineering time to run upgrades,
capacity and HA. Managed options move that to a usage bill:

- **Amazon Managed Service for Prometheus (AMP):** billed on samples ingested,
  storage and query samples. Rule evaluation and alerting are supported
  (rules and Alertmanager config uploaded per workspace), so the generated
  rule files can be used as they are. Remote write from the Collector with SigV4.
- **Amazon Managed Grafana (AMG):** billed per active editor / viewer user.
  The generated dashboards import as they are; the datasource becomes AMP.
- Grafana Cloud, and other hosted Prometheus-compatible services, follow the
  same series / samples / GB model.

Rule of thumb for the decision: managed wins when the team is small or
observability isn't the product; self-hosted wins at high, steady volume with a
team already running stateful systems. Either way, cardinality control is the
largest lever, and it costs nothing but discipline.

## Illustrative sizing

For a small platform (a few services, 200k active series, 30s scrape, 15d
local retention): about 6,700 samples/s, roughly 1-2 bytes per sample
compressed, so on the order of 10-20 GB of local TSDB. A single Prometheus
with 4-8 GB RAM handles it. These are round numbers to reason with, not a quote.
