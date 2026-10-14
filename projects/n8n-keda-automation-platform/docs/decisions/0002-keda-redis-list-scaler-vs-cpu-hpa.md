# ADR 0002: Scale workers with KEDA's Redis list scaler, not a CPU HPA

- Status: accepted
- Date: 2026-10-14

## Context

Workers are where cost and capacity live. Their load is the queue, not their
CPU: most n8n executions wait on HTTP calls to other services, so a worker
with all ten concurrency slots busy can sit at 5% CPU while jobs pile up
behind it. And a plain HPA can't go below one replica.

## Decision

A KEDA `ScaledObject` on the worker Deployment with two `redis` triggers:

| Trigger | List | Target (`listLength`) | Purpose |
|---|---|---|---|
| `bull-wait` | `bull:jobs:wait` | 10 per worker | backlog: add workers as jobs queue up |
| `bull-active` | `bull:jobs:active` | worker concurrency (10) | in-flight: keep workers that are running jobs |

`minReplicaCount: 0`, `maxReplicaCount: 10` (30 in prod), `pollingInterval: 15`,
`cooldownPeriod: 300`, `activationListLength: 0`, scale-down stabilization
300s with at most -50% per minute, scale-up at most +4 pods per 15s.

The key comes from n8n's code, not a guess: Bull keys are
`<prefix>:<queue>:<type>`, the prefix is `QUEUE_BULL_PREFIX` (default `bull`)
and the queue is the constant `jobs`. Observed locally: with no worker, three
webhook calls gave `LLEN bull:jobs:wait = 3`.

## Why the second trigger

Bull moves a job from `wait` to `active` the moment a worker takes it
(`RPOPLPUSH` in `moveToActive`). Observed locally: wait 0, active 3 while
three executions ran. With the wait trigger alone, a burst of long jobs looks
like an idle queue as soon as it's picked up: the HPA scales in and, after the
cooldown, KEDA scales to zero while the jobs run. The worker's graceful
shutdown would let them finish, but the scale-in itself is wrong, and new jobs
arriving then wait for a cold start. The HPA takes the maximum of the two
proposals, so running jobs hold `ceil(active / concurrency)` workers. The
simulator test `test_active_trigger_holds_workers_while_jobs_run` shows the
difference.

## Consequences

- Scale to zero: worker cost tracks demand ([cost](../cost.md)).
- Cold start: the first job after idle waits for a poll (up to 15s) plus pod
  start (image pull, CSI mount, n8n boot). Acceptable for asynchronous work;
  for latency-sensitive hours, add a KEDA `cron` trigger to hold one worker.
- Correctness depends on the list key. A wrong key never errors: it measures
  an empty list and never activates. `check_chart_policy.py` CP009 and the
  schema's no-braces rule on `queue.bullPrefix` guard the chart side.
- KEDA needs the Redis password: [ADR 0003](0003-trigger-authentication-secrets.md).
- `scripts/keda_scaling_sim.py` models these settings, so they can be tuned
  offline. It is a model of documented semantics, not KEDA.

## Alternatives considered

- **CPU HPA (min 1).** Scales on the wrong signal, never reaches zero, and
  under-provisions I/O-bound work.
- **HPA on n8n's queue metrics through Prometheus Adapter.** n8n can export
  queue metrics (`N8N_METRICS_INCLUDE_QUEUE_METRICS`), but that adds Prometheus
  and an adapter to the scaling path, and still can't scale to zero.
- **KEDA `prometheus` scaler on the same metric.** Works, and supports zero,
  but depends on the main process (which exports the queue metrics) and on
  Prometheus being up. Reading Redis directly has fewer dependencies.
