# Runbook: game day

> A game day is how the durations in the other runbooks, which are
> targets to measure, become measured numbers. This page is the plan for
> one. The outputs below are real output of the CLI's fake adapters,
> which are also how to rehearse the commands before the first real
> exercise. **No results are claimed:**
> fill in the table at the end from your own exercise.

## Goals

1. Measure, don't assume: time to detect, time to decide, time per step,
   data loss in the unplanned case, and time until error rates recover.
2. Prove that the guards fire: lag threshold, confirm token, split brain,
   failback without a rebuild.
3. Exercise the runbooks as written, and fix the runbooks, not the people.

## Roles

| Role | Does |
|---|---|
| Game master | Injects the failure, keeps time, can stop the exercise |
| Incident commander | Declares (or declines) failover, following the runbooks |
| Operator | Runs the CLI; reads each step aloud |
| Scribe | Timestamps every decision; owns the results table |
| Observer (service owner) | Watches customer-facing signals |

## Stop conditions

Stop and roll back if customer-facing error rates in a *production*
exercise exceed the agreed budget, if the DR region fails its own health
check, or if anyone is unsure what state the system is in.
`failover status` must be clean before you start.

## Scenarios

### 0. Rehearse with fakes (anyone, any time)

The guards, in order. Planned mode with lag above the threshold is
refused and nothing changes:

```text
$ PYTHONPATH=src python3 -m failover --scenario lagging execute --mode planned --confirm dr-app-global --target us-west-2
Run 20261014T071943Z-planned-us-west-2: planned failover us-east-1 -> us-west-2
[1/6] precheck        FAILED: replication lag into us-west-2 is 42.0s, at or above the 5s threshold; wait for it to drop or investigate before switching over
error: replication lag into us-west-2 is 42.0s, at or above the 5s threshold; wait for it to drop or investigate before switching over
(exit 4)
```

A wrong confirm token (one letter off) is refused:

```text
$ PYTHONPATH=src python3 -m failover execute --mode planned --confirm dr-app-globl --target us-west-2
error: confirm token 'dr-app-globl' does not match the global cluster id 'dr-app-global'
(exit 2)
```

Two writers that nobody fenced (someone promoted DR by hand) block every
failover, and `status` says so:

```text
$ PYTHONPATH=src python3 -m failover --scenario split-brain status
Global cluster dr-app-global  record orders.example.com
Aurora global writer: us-east-1   writers now: us-east-1, us-west-2   DNS PRIMARY: us-east-1   state: writer us-east-1, epoch 0

REGION      DEPLOYED AS  HEALTH       AURORA              LAG     DNS        WORKERS  API MIN  FENCED
us-east-1   primary      healthy      writer (global)     -       PRIMARY    2        3        no
us-west-2   dr           healthy      writer (detached)   -       SECONDARY  0        2        no

Warnings:
  ! SPLIT BRAIN: us-east-1, us-west-2 accept writes and none is fenced
(exit 0)
```

```text
$ PYTHONPATH=src python3 -m failover --scenario split-brain execute --mode planned --confirm dr-app-global --target us-west-2
error: split brain refused: us-east-1, us-west-2 accept writes and none is fenced. Stop writes in one of them and fence it before failing over
(exit 3)
```

Unplanned failover refuses to run while the primary is healthy:

```text
$ PYTHONPATH=src python3 -m failover execute --mode unplanned --confirm dr-app-global --target us-west-2
Run 20261014T071943Z-unplanned-us-west-2: unplanned failover us-east-1 -> us-west-2
[1/6] precheck        FAILED: us-east-1 is healthy; an unplanned failover would discard un-replicated writes for nothing. Use --mode planned
error: us-east-1 is healthy; an unplanned failover would discard un-replicated writes for nothing. Use --mode planned
(exit 4)
```

The full flows are in [planned-failover.md](planned-failover.md),
[unplanned-failover.md](unplanned-failover.md) and
[failback.md](failback.md). The resume-after-crash behaviour is covered
by `tests/test_orchestrator.py` (`ResumeTests`), because the CLI's fakes
don't inject crashes.

### 1. Planned failover and failback (staging first, then production)

Follow [planned-failover.md](planned-failover.md), wait an agreed period,
then [failback.md](failback.md) section 3. Measure the write-interruption
window from the application's side: count failed writes per second at the
ALB or in app metrics. Don't rely on the CLI's timestamps alone.

### 2. Unplanned failover (staging only, until scenario 1 is routine)

Inject: block the primary region at the network level for the app (for
example, a security group or NACL change on the data subnets and the
ALB), **not** by deleting anything. Then follow
[unplanned-failover.md](unplanned-failover.md) from detection onwards.
Measure:

- detection time (alarm to page);
- decision time (page to `execute`);
- data loss: write a sequence of numbered test orders at a steady rate
  before and during the injection, then count which ones exist in
  us-west-2 after promotion. That number, not the lag metric, is your
  observed RPO for this exercise;
- cache cold-start impact: p95 latency and Aurora CPU in the first 15
  minutes;
- worker duplicates: replay the last hour of jobs in us-west-2 and
  confirm every one is `skipped-duplicate` (the idempotency check).

### 3. Half-alive primary

Inject: degrade rather than block (add latency and packet loss to the
primary's EKS API). This is the case where fencing is slowest
([ADR 0005](../docs/decisions/0005-fencing-before-promotion.md)). Measure how
long `helm upgrade --wait` takes to fail, and whether the team picks
planned or unplanned mode correctly.

## Results (fill in per exercise)

| Measure | Target to measure | Observed | Notes |
|---|---|---|---|
| Detection | about 1.5 min | | |
| Decision | under 15 min | | |
| Fence | under 2 min | | |
| Promote (switchover / detach) | minutes | | |
| Scale-up | under 5 min | | |
| DNS: 95% of clients on DR | TTL + interval | | |
| Write-interruption window (planned) | as short as possible | | |
| Orders lost (unplanned) | measured, not assumed | | |
| Duplicate job executions | 0 | | |

Write each exercise up with the audit log attached, and change the
targets in the runbooks to the numbers you can defend.
