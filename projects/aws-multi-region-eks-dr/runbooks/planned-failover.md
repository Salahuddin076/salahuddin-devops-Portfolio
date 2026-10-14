# Runbook: planned failover (us-east-1 -> us-west-2)

> Reference runbook, rehearsed only against the CLI's fake adapters. The
> outputs below are real output of those fakes. Durations are **targets to
> measure** in your own game days, not results.

## When to use it

- Moving the writer ahead of a known risk: an AWS-announced regional
  event, risky maintenance in the primary, a degradation that is getting
  worse but still works.
- Drills (see [game-day.md](game-day.md)).
- Both regions are healthy, and replication lag is below
  `max_replication_lag_seconds` (5 s by default). If the primary is down
  or unreachable, use [unplanned-failover.md](unplanned-failover.md).

## When not to

- **A partial, application-level problem.** A bad deploy, a slow query
  or a noisy neighbour follows the code and the data to the DR region.
  Roll back first.
- **Replication lag is high.** The pre-check refuses, and it is right to:
  find out why first (a long transaction, a write burst, storage limits).
- **The DR region shows any warning in `status`.** Fix the standby before
  you rely on it.
- **Nobody owns the decision.** See below.

## Who decides

The **incident commander** declares a planned failover after hearing from
the database owner (lag, long transactions) and the service owner (open
deploys, feature flags). Customer-facing impact is a short window of
read-only writes during the switchover, so tell support first. One person
runs the CLI; a second person reads every step as it prints.

## Expected durations (targets to measure)

| Phase | Target to measure |
|---|---|
| Decision to `execute` | under 15 min |
| Pre-checks + fence | under 2 min |
| Managed switchover | a few minutes; writes fail while it runs |
| Scale-up in DR | under 5 min (depends on node scale-up) |
| DNS flip until most clients move | TTL + health-check interval |
| Post-checks | under 2 min |

## Steps

1. **Look before you act.** Both regions should be healthy, lag low, no
   warnings.

```text
$ PYTHONPATH=src python3 -m failover status
Global cluster dr-app-global  record orders.example.com
Aurora global writer: us-east-1   writers now: us-east-1   DNS PRIMARY: us-east-1   state: writer us-east-1, epoch 0

REGION      DEPLOYED AS  HEALTH       AURORA              LAG     DNS        WORKERS  API MIN  FENCED
us-east-1   primary      healthy      writer (global)     -       PRIMARY    2        3        no
us-west-2   dr           healthy      secondary (global)  0.4s    SECONDARY  0        2        no

Warnings: none
(exit 0)
```

2. **Read the plan aloud.** Nothing is executed.

```text
$ PYTHONPATH=src python3 -m failover plan --mode planned
Plan: planned failover us-east-1 -> us-west-2  (global cluster dr-app-global)
  1. precheck        us-west-2 deep health OK; us-east-1 healthy (planned needs both); Aurora
                     global writer is us-east-1 and us-west-2 is a member; replication lag into
                     us-west-2 < 5s
  2. fence-source    scale workers to 0 in us-east-1 (helm: workers.enabled=false); mark
                     us-east-1 fenced in the state file. Must succeed in planned mode
  3. promote-target  failover-global-cluster --switchover to dr-app-us-west-2 (managed
                     switchover: waits for replication to catch up, no data loss; us-east-1
                     becomes a secondary)
  4. scale-target    us-west-2: HPA minReplicas 3, workers.enabled=true, workers.replicas=2
  5. flip-dns        Route 53 orders.example.com: us-west-2 -> PRIMARY, us-east-1 -> SECONDARY
                     (one change batch)
  6. postcheck       us-west-2 healthy, a writer, PRIMARY in DNS, workers > 0; no unfenced second
                     writer; workers 0 in us-east-1 if reachable
Notes:
  - execute needs: --confirm dr-app-global
Nothing was executed.
(exit 0)
```

3. **Announce** in the incident channel: planned failover to us-west-2,
   expected write interruption, the run will be resumed from the same
   command if anything fails.

4. **Execute.** The confirm token is the global cluster ID. Pass
   `--target` explicitly so a re-run is unambiguous.

```text
$ PYTHONPATH=src python3 -m failover execute --mode planned --confirm dr-app-global --target us-west-2
Run 20261014T071743Z-planned-us-west-2: planned failover us-east-1 -> us-west-2
[1/6] precheck        done: us-west-2 healthy, us-east-1 healthy, writer us-east-1, lag 0.4s < 5s
[2/6] fence-source    done: workers in us-east-1 scaled to 0; us-east-1 marked fenced
[3/6] promote-target  done: managed switchover complete: dr-app-us-west-2 is the global writer; epoch 1
[4/6] scale-target    done: us-west-2: API min replicas 3, workers 2
[5/6] flip-dns        done: us-west-2 is PRIMARY, us-east-1 is SECONDARY
[6/6] postcheck       done: us-west-2 healthy, writer, PRIMARY, 2 workers
Completed: us-west-2 is the writer (epoch 1); us-east-1 is fenced
(exit 0)
```

5. **Verify.** us-west-2 is the writer and PRIMARY in DNS. us-east-1 is a
   healthy secondary, fenced, with 0 workers.

```text
$ PYTHONPATH=src python3 -m failover status
Global cluster dr-app-global  record orders.example.com
Aurora global writer: us-east-1   writers now: us-east-1   DNS PRIMARY: us-east-1   state: writer us-west-2, epoch 1

REGION      DEPLOYED AS  HEALTH       AURORA              LAG     DNS        WORKERS  API MIN  FENCED
us-east-1   primary      healthy      writer (global)     -       PRIMARY    2        3        yes
us-west-2   dr           healthy      secondary (global)  0.4s    SECONDARY  0        2        no

Warnings:
  ! us-east-1 is fenced but runs 2 workers: scale them to 0 now
  ! us-east-1 is fenced but its cluster still accepts writes: rebuild it as a secondary before it rejoins (runbooks/failback.md)
  ! DNS PRIMARY is us-east-1 but the state's writer is us-west-2
(exit 0)
```

6. **Watch for 30 minutes:** error rate and latency on the DR ALB, Aurora
   CPU and connections in us-west-2 (the cache is cold), and job backlog.

## If a step fails

- The run stops at the failed step and the state file records it. Fix
  the cause and **re-run the exact same `execute` command**. Steps already
  done are skipped and logged as `step_resume_skip`. Nothing that
  succeeded runs twice.
- **Pre-check failed:** nothing changed, and the run is closed as aborted.
- **Fence failed** (us-east-1's EKS API unhealthy): in planned mode this
  stops the run before the database is touched. Reconsider whether this
  is really a planned failover.
- **Switchover failed or timed out:** check
  `aws rds describe-global-clusters`. If the writer moved, the resumed
  promote step sees it and records "already the global writer".
- **DNS step failed:** Route 53's control plane is in us-east-1. Retry. If
  it keeps failing, traffic is still on us-east-1, whose database is now a
  read-only secondary: writes fail until the record changes. Escalate to
  AWS support while retrying.

## Afterwards

- The audit log (`.failover/audit.jsonl` or your configured location)
  is the timeline for the review.
- Lower us-east-1's API minimum if you want to save cost while it is the
  standby (`helm upgrade --reuse-values --set api.autoscaling.minReplicas=2`).
- Failing back is another planned switchover: [failback.md](failback.md).
