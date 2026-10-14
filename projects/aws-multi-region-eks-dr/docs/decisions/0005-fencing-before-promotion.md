# ADR 0005: Fence the old primary before promoting the new one

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-multi-region-eks-dr (reference implementation)

## Context

The dangerous failure in a two-region database setup is not the outage
itself. It is two writers. If both regions accept writes, even for a few
minutes, orders are taken against stock that the other region has
already sold, the same job is processed twice, and the two databases
diverge in ways no tool reconciles automatically.

Two writers can come about in several ways:

- **Unplanned failover, then the old region recovers.** After detach and
  promote, the old primary is still a writable cluster
  ([ADR 0002](0002-managed-switchover-vs-detach-promote.md)). Its pods
  come back, its workers resume, and the Route 53 record still exists.
- **Workers keep running in the old region during a planned failover.**
  After the switchover their database is read-only, so writes fail, but
  in-flight jobs may already have had external side effects (a payment
  captured) that are then retried in the new region.
- **Two operators, two terminals.** One fails over to us-west-2 while
  the other, working from an older picture, tries to "fix" things by
  promoting us-east-1.

## Decision

The failover orchestrator fences before it promotes, and refuses anything
that could produce a second writer.

1. **Fence first (step 2, before promote).** It scales the old writer
   region's workers to 0 (`helm upgrade --reuse-values --set
   workers.enabled=false`) and marks the region `fenced` in the state
   file.
   - **Planned mode:** fencing must succeed, or the run stops before
     touching the database.
   - **Unplanned mode:** if the old region's EKS API doesn't answer, the
     step is recorded as **skipped**, with `workers_confirmed_zero:
     false`, and the region is marked fenced anyway. The audit log, the
     state file and `status` all show that the workers are unconfirmed.
     The runbook's "Fence later" section says what to do before that
     region rejoins.
2. **DNS follows the writer.** The flip-dns step makes the promoted
   region's record PRIMARY and the old one SECONDARY. Terraform ignores
   the routing policy after the first apply, so a routine apply can't
   move traffic back to a fenced region.
3. **Guards before any step:**
   - The confirm token must equal the global cluster ID, which stops a
     run aimed at the wrong environment.
   - If an unfinished run already promoted the other region, the CLI
     refuses (`SplitBrainRefused`) and tells you to resume that run.
   - If the database reports more than one writer and none is fenced, the
     CLI refuses (`SplitBrainRefused`). `status` shows `SPLIT BRAIN`.
   - Moving the writer back to a fenced region is a failback, and it
     needs `--rebuild-confirmed`. The pre-check then verifies that the
     region really is a secondary of the current writer.
4. **Workers check twice.** Every job carries an idempotency key that is
   claimed in a replicated table before any work starts
   (`src/worker_idempotency.py`). A job that is redelivered or replayed
   after failover is skipped. A worker in a fenced region refuses to
   process at all. A late completion from an older epoch is discarded.

## Consequences

- **Fencing is the slowest step when the old region is half-alive.** A
  `helm upgrade --wait` against a degraded cluster can take minutes. If
  it hangs in unplanned mode, an operator can let it time out: the step
  then fails and the run can be resumed, or the operator can switch to
  treating the region as unreachable. The game day measures this.
- **The state file is now critical.** It must be readable from either
  region during an outage of the other. The reference writes a local
  path. Real use needs an S3 bucket outside the failed region, ideally a
  third region with versioning, and object lock on the audit log.
- **The fence is a promise, not a lock.** Nothing in AWS prevents
  someone from running `helm upgrade --set workers.enabled=true` in a
  fenced region by hand. The NOTES.txt, the runbooks and `status` warn
  against it. A stronger fence (an SCP or permission boundary that blocks
  `rds-db:connect` to the old cluster, or a database role revoked on the
  old writer) is listed as a follow-up in [security.md](../security.md).
- **The idempotency check has the same RPO gap as the database.** A claim
  that didn't replicate before an unplanned failover is lost, and the job
  runs again in DR. The test
  `test_unreplicated_claim_is_reprocessed_documented_rpo_gap` pins this
  behaviour down. Downstream calls carry the same key so that the
  provider deduplicates.
