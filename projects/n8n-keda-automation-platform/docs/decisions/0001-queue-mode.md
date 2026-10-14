# ADR 0001: Run n8n in queue mode with separate main, webhook and worker processes

- Status: accepted
- Date: 2026-10-14

## Context

n8n's default ("regular") mode runs everything in one process: the editor,
the REST API, schedules, webhook handling and every execution. That process
can't be replicated (two would both fire every schedule), so the only way to
add capacity is a bigger pod, and one heavy workflow slows the editor and
webhook responses for everyone.

The platform needs to absorb bursts of webhook-triggered executions, keep
webhook latency low while executions are slow, and cost little when idle.

## Decision

Run `EXECUTIONS_MODE=queue` with three Deployments from one pinned image:

- **main** (`n8n start`), one replica, `Recreate`: editor, API, schedules,
  pollers, test webhooks, DB migrations. `N8N_DISABLE_PRODUCTION_MAIN_PROCESS=true`
  keeps production webhooks off it.
- **webhook** (`n8n webhook`), HPA on CPU: accepts production webhooks and
  enqueues one Bull job per execution in Redis.
- **worker** (`n8n worker --concurrency=10`), KEDA-scaled from 0: takes jobs,
  runs them, writes results to Postgres.
- `OFFLOAD_MANUAL_EXECUTIONS_TO_WORKERS=true` so editor test runs also go
  through the queue (n8n 2.41 marks running them on main as deprecated).

Postgres is mandatory (queue mode doesn't support SQLite), and Redis
(ElastiCache Valkey here) carries both the queue and n8n's pub/sub between
processes.

## Consequences

- Webhook latency is decoupled from execution time: a webhook pod answers as
  soon as the job is queued (for workflows that respond immediately).
- Workers scale independently and can go to zero
  ([ADR 0002](0002-keda-redis-list-scaler-vs-cpu-hpa.md)).
- Main stays a singleton. A main outage stops schedules and the editor, but
  not webhooks or running executions. Removing that limit needs n8n's licensed
  multi-main mode (`N8N_MULTI_MAIN_SETUP_ENABLED`, leader election in Redis),
  which this design doesn't assume.
- Three moving parts instead of one: version skew between them is a real
  failure mode, so upgrades stop workers first and let main migrate
  ([operations](../operations.md#upgrading-n8n)).
- Redis becomes critical: if it is down, webhooks fail to enqueue. Hence the
  Multi-AZ replication group.
- Execution is at-least-once: a worker crash can lead to a retried execution,
  so side effects need idempotency (`scripts/duplicate_job_guard.py`).

## Alternatives considered

- **Regular mode, bigger pod.** Simple, but no horizontal scaling, no scale to
  zero, and one bad workflow degrades everything.
- **Queue mode without webhook processes** (main takes webhooks). One fewer
  Deployment, but webhook traffic then competes with the editor and the
  singleton becomes the ingress bottleneck.
