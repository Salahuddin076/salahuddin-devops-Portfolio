# ADR 0002: Managed switchover for planned failover, detach and promote for unplanned

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-multi-region-eks-dr (reference implementation)

## Context

Aurora Global Database gives three ways to move the writer to the secondary
region:

1. **Managed switchover** (`failover-global-cluster --switchover`, also
   exposed as `switchover-global-cluster`). Aurora waits until the
   secondary has caught up, demotes the old primary, promotes the
   secondary, and keeps both clusters in the same global cluster with
   their roles swapped. No committed write is lost. It needs both regions
   to be healthy.
2. **Managed failover with data loss** (`failover-global-cluster
   --allow-data-loss`). Aurora promotes the secondary without waiting. When
   the old primary comes back, Aurora tries to rejoin it as a secondary of
   the new writer. Writes that never replicated are lost.
3. **Detach and promote** (`remove-from-global-cluster` on the secondary).
   The secondary leaves the global cluster and becomes a standalone,
   writable cluster at once. The old primary is left alone. If it comes
   back, it is still a writer, and nothing reconnects it.

## Decision

- **Planned mode uses managed switchover.** It covers drills, region
  evacuations ahead of maintenance, and a degraded but working primary.
  Pre-checks require both regions healthy and replication lag below
  `max_replication_lag_seconds` (5 s by default), so the switchover does
  not stall waiting for a lagging secondary.
- **Unplanned mode uses detach and promote.** It covers a primary that is
  down or unreachable. The orchestrator calls `remove-from-global-cluster`
  on the DR cluster, waits until that cluster is a standalone writer
  (status `available`, no global cluster identifier), and records the last
  known replication lag as the run's `rpo_exposure_seconds`.

## Why detach and promote over managed failover for unplanned

The managed failover option is the more automated choice, and AWS
recommends it for many cases. This project uses detach and promote for
three reasons tied to the fencing design ([ADR 0005](0005-fencing-before-promotion.md)):

- **Nothing rejoins without a person deciding.** After a regional event,
  the old primary may hold writes that never replicated. Detach and promote
  leaves it isolated. The [failback runbook](../../runbooks/failback.md)
  makes someone decide what happens to those writes (export them for
  reconciliation, or accept the loss) before the cluster is deleted and
  rebuilt as a secondary. The failover CLI refuses a failback without
  `--rebuild-confirmed` and checks that the old region really is a
  secondary again.
- **It needs nothing from the failed region.** The call goes to the DR
  region's RDS endpoint about the DR cluster. Managed failover meets this
  requirement too, so it is a requirement, not a tie-breaker.
- **The end state is easy to see.** Two clusters, one of them fenced. The
  CLI's `status` shows the fenced old writer explicitly and warns until it
  is rebuilt.

Revisit this if rehearsals show the manual rebuild takes longer than the
failback window allows. Managed failover is one adapter method away:
`AuroraGlobal.detach_and_promote` can be replaced with
`failover_global_cluster(AllowDataLoss=True)`.

## RPO implication

| Mode | Data loss | Why |
|---|---|---|
| planned (switchover) | none | Aurora waits for the secondary to catch up before promoting |
| unplanned (detach + promote) | writes committed in the primary but not yet replicated | replication is asynchronous; the loss window is the lag at the moment of failure |

The lag is measured by `AuroraGlobalDBReplicationLag` on the secondary.
It is alarmed in Terraform (`replication_lag_alarm_seconds`) and shown by
`failover status`. No figure is claimed here: measure it in your own game
days ([runbooks/game-day.md](../../runbooks/game-day.md)).

S3 Cross-Region Replication is also asynchronous, with a separate window
(up to 15 minutes for 99.99% of objects when Replication Time Control is
on). Writes to Valkey are lost by design ([ADR 0003](0003-valkey-rebuildable.md)).

## Consequences

- Terraform drifts after an unplanned failover. The DR cluster no longer
  belongs to the global cluster, and `global_cluster_identifier` is in
  `ignore_changes` so an apply doesn't try to re-attach it. Rebuilding the
  topology is a runbook procedure with explicit state moves, not a side
  effect of `terraform apply`.
- After a planned switchover the topology is intact. The old primary is a
  healthy secondary, and failback is another planned switchover (still
  gated by `--rebuild-confirmed`, which then only confirms what the
  pre-check verifies).
