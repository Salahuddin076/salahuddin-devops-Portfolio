# ADR 0004: RDS PostgreSQL (Multi-AZ instance), not Aurora Serverless v2

- Status: accepted
- Date: 2026-10-14

## Context

Postgres holds everything durable in n8n: workflows, encrypted credentials,
users and execution history. The load is modest and steady: main polls and
serves the editor, webhook pods create execution rows, and workers write
execution data. Writes grow with executions; pruning
(`EXECUTIONS_DATA_MAX_AGE`, `EXECUTIONS_DATA_PRUNE_MAX_COUNT`) keeps the
tables bounded. There is one writer and no need for read replicas.

## Decision

`aws_db_instance` running PostgreSQL 16 on db.t4g.medium, gp3 with storage
autoscaling, Multi-AZ, CMK encryption, 14-day automated backups (7 at least,
by validation), deletion protection, a final snapshot, `rds.force_ssl = 1`.
The master password is RDS-managed (`manage_master_user_password`) and n8n
connects as a separate application role.

## Why not Aurora Serverless v2

- **It wouldn't scale to zero here.** Aurora Serverless v2 can auto-pause at
  0 ACU, but only with no connections. n8n's main keeps a pool open
  permanently (and pings it, `DB_PING_INTERVAL_SECONDS`), so the cluster never
  pauses, and a resume would take seconds that webhooks can't wait anyway.
- **Steady small load favours a fixed instance.** At a constant 1-2 ACU
  floor, Serverless v2 costs about as much as, or more than, a t4g.medium
  Multi-AZ instance, before Aurora's I/O or storage charges ([cost](../cost.md)).
- **Failover is good enough on RDS Multi-AZ.** n8n's DB client reconnects
  after a failover (`DB_PING_*` recovery settings); the Aurora advantage
  (faster failover, readers) buys little for one writer.

Where Aurora would win: many n8n instances sharing one cluster, spiky
reporting queries that justify readers, or a need for Global Database.

## Consequences

- Vertical scaling is a modification with a short Multi-AZ failover.
- The master secret is RDS's (rotated by RDS on its schedule). n8n never reads
  it, so that rotation never restarts n8n. The application role's password
  rotates by hand (or with a rotation Lambda the module doesn't include) plus
  a rollout, because n8n reads `_FILE` values once at start.
- `skip_final_snapshot = false` and deletion protection make tearing down a
  test environment a two-step job, on purpose.
