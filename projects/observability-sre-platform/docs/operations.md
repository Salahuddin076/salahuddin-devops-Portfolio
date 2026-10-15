# Operations

All commands run from `projects/observability-sre-platform/`.

## Adding or changing an SLO

1. Add or edit `slo/<service>.json`. Each SLO needs:
   - `name` (slug), `objective` (percent, e.g. `99.9`), `window` (`28d` or `30d`);
   - `sli.good` and `sli.total`: PromQL that **aggregates to a single series**
     (a `sum(...)` without `by`) and contains `[$window]` where the range goes;
   - `alerting.tiers`: any of `page-1h`, `page-6h`, `ticket-1d`, `ticket-3d`;
   - `alerting.runbook`: slug for `runbooks/<slug>-fast-burn.md` and `-slow-burn.md`.
2. Write the two runbooks (a test fails if an alert's runbook file is missing).
3. Regenerate and check:

   ```bash
   python3 generator/slogen.py generate
   python3 generator/slogen.py explain        # thresholds and budget math per tier
   python3 -m unittest discover -s tests -v
   ```

4. Add a promtool case to `tests/promtool/slo-alerts.test.yml` with the
   expected alert computed by hand, and run promtool (below).
5. Commit `slo/`, `generated/` and the runbooks together. CI fails if
   `generated/` doesn't match the SLO files.

Choosing the SLI: count events the user would notice. `good` and `total` must
come from the same source, so the ratio is meaningful. Good SLIs are a
request-success ratio, a latency-bucket ratio (`le` must be an existing
bucket, and Prometheus 3 normalises `le="300"` to `le="300.0"`), a freshness
histogram, or probe success.

Why `or vector(0)`: in a total outage the "good" series may not exist at all
(`code!~"5.."` matches nothing). Without the fallback, the ratio would be empty
and no alert would fire; a promtool case covers it.

## Tuning thresholds

- Start with the workbook tiers. Change them only with data: run
  `slogen.py report` over exported hourly counts to see which alerts would
  have fired for past incidents and how much budget they cost.
- **Too many pages for small blips:** raise `for:` on page-1h a little, or
  lower the objective if users don't notice. Don't drop the short window; it
  is what makes alerts resolve quickly.
- **Low traffic:** at a few requests per minute, one failure is a large
  ratio. Options: a longer short window, a minimum-traffic condition
  (`and sum(rate(total[1h])) > N`), or synthetic probes to add traffic.
- **28-day windows:** the same factors spend slightly more budget per window
  (14.4x over 1h = 2.14% of 28d); the generated descriptions show the real figure.
- `slo:sli_error:ratio_rate30d` is an unweighted mean of 5m ratios; with very
  uneven traffic it over-weights quiet hours. If that matters, record
  `increase()` sums of good and total over the window instead (more expensive).

## Silencing

Silence by `service` and `slo`, with an end time and a comment naming the
change or incident:

```bash
amtool silence add service=checkout-api slo=availability \
  --duration=2h --comment="CHG-1234 planned DB failover" \
  --alertmanager.url=http://alertmanager.observability.svc:9093
amtool silence query
amtool silence expire <id>
```

Never silence `Watchdog`. A silence doesn't stop budget burn: planned
maintenance still spends budget unless the error-budget review excludes it.

## Testing alerts with promtool

```bash
# syntax and PromQL of every generated rule
docker run --rm -v "$PWD:/work:ro" -w /work --entrypoint promtool \
  prom/prometheus:v3.5.0 check rules generated/prometheus/*.rules.yml
# unit tests: synthetic series in, expected alerts out
docker run --rm -v "$PWD:/work:ro" -w /work --entrypoint promtool \
  prom/prometheus:v3.5.0 test rules tests/promtool/slo-alerts.test.yml
```

`python3 -m unittest` runs both when docker and the image are present locally.
The promtool cases cover: constant 50x burn (both pages, then tickets after
their 15m `for`), healthy 0.5x (nothing fires), total outage with no good
series, the short window resetting a page, latency 2x (only the 1x ticket),
orders freshness, website probes, and Watchdog.

## Local demo

```bash
docker compose up -d
curl -X POST 'http://127.0.0.1:8080/fault?checkout_errors=0.2'   # 200x burn
# after about 2.5 minutes:
curl -s http://127.0.0.1:9090/api/v1/alerts | python3 -m json.tool
curl -s http://127.0.0.1:8080/alerts                              # what Alertmanager sent
open http://127.0.0.1:3000                                        # Grafana, SLO folder
curl -X POST 'http://127.0.0.1:8080/fault?checkout_errors=0'
docker compose down
```

Faults: `checkout_errors`, `checkout_slow`, `orders_late`, `website_down`
(ratios 0..1). The ticket alerts fire after their 15m `for` and are then
inhibited by the page in Alertmanager.

## Deploying to a cluster (reference)

Prerequisite: the Prometheus Operator (for example kube-prometheus-stack) with
selectors matching `prometheus: platform`, a blackbox exporter, and the
`alertmanager-receivers` Secret created by External Secrets.

```bash
helm upgrade --install obs helm/observability-stack -n observability
kubectl apply -n observability -f generated/kubernetes/
```

Then set `spec.alertmanagerConfiguration.name: slo-routing` on the
Alertmanager resource so the routing is global (otherwise the operator adds a
`namespace` matcher and the SLO alerts don't match). Not exercised here.
