# Runbook: unplanned failover (us-east-1 lost)

> Reference runbook, rehearsed only against the CLI's fake adapters. The
> outputs below are real output of those fakes (scenario `primary-down`).
> Durations are **targets to measure**, not results. Unplanned failover
> **loses writes that had not replicated**: no RPO figure is claimed.

## When to use it

us-east-1 is down or unreachable for the service: the deep health check
fails, the regional EKS API or Aurora writer doesn't answer, and AWS
Health or your own probes confirm a regional problem, not a bad deploy.

## When not to

- **The primary is healthy** but something else is broken. The CLI's
  pre-check refuses unplanned mode while the source health check passes;
  use the planned runbook, or roll back.
- **It looks like a short blip.** Route 53 is already sending traffic to
  us-west-2 while us-east-1's health check fails, and reads work there.
  Writes do not, because the DR database is still a read-only secondary.
  If AWS expects recovery within your write-outage tolerance, waiting can
  cost less than losing the un-replicated tail and then rebuilding. The
  incident commander makes that call, with the lag figure from `status`
  in front of them.
- **You can't reach the state file.** Fix that first. Running without
  the shared state removes the split-brain guards.

## Who decides

The **incident commander** declares it, with the database owner present.
Write down in the incident channel, before executing, the last known
replication lag: that is the size of the data you are choosing to lose.
The decision should name a time limit ("if us-east-1 is not back by
10:40, we fail over").

## Expected durations (targets to measure)

| Phase | Target to measure |
|---|---|
| Detection (health-check alarms) | failure_threshold x interval, about 1.5 min at the defaults |
| Decision | under 15 min, bounded by the agreed time limit |
| Detach + promote | a few minutes |
| Scale-up in DR | under 5 min, more if EC2 capacity is tight |
| DNS flip | already serving DR because of the health checks; the flip makes it stick |

## Steps

1. **Status.** us-east-1 unreachable, us-west-2 healthy, last lag shown.

```text
$ PYTHONPATH=src python3 -m failover --scenario primary-down --fake-world outage.json status
Global cluster dr-app-global  record orders.example.com
Aurora global writer: us-east-1   writers now: us-east-1   DNS PRIMARY: us-east-1   state: writer us-east-1, epoch 0

REGION      DEPLOYED AS  HEALTH       AURORA              LAG     DNS        WORKERS  API MIN  FENCED
us-east-1   primary      unreachable  writer (global)     -       PRIMARY    -        -        no
us-west-2   dr           healthy      secondary (global)  1.2s    SECONDARY  0        2        no

Warnings:
  ! the writer region us-east-1 is unreachable: declare or rule out an incident before acting (runbooks/unplanned-failover.md)
(exit 0)
```

2. **Plan.**

```text
$ PYTHONPATH=src python3 -m failover --scenario primary-down --fake-world outage.json plan --mode unplanned
Plan: unplanned failover us-east-1 -> us-west-2  (global cluster dr-app-global)
  1. precheck        us-west-2 deep health OK; us-east-1 unhealthy or unreachable (if it is
                     healthy, use planned); Aurora global writer is us-east-1 and us-west-2 is a
                     member; last known lag recorded as the RPO exposure
  2. fence-source    scale workers to 0 in us-east-1 if its EKS API answers; if not, record
                     SKIPPED (workers not confirmed at 0) and mark us-east-1 fenced anyway
  3. promote-target  remove-from-global-cluster dr-app-us-west-2, wait until it is a standalone
                     writer (writes not yet replicated from us-east-1 are lost: RPO = lag at
                     failure time)
  4. scale-target    us-west-2: HPA minReplicas 3, workers.enabled=true, workers.replicas=2
  5. flip-dns        Route 53 orders.example.com: us-west-2 -> PRIMARY, us-east-1 -> SECONDARY
                     (one change batch)
  6. postcheck       us-west-2 healthy, a writer, PRIMARY in DNS, workers > 0; no unfenced second
                     writer; workers 0 in us-east-1 if reachable
Notes:
  - execute needs: --confirm dr-app-global
  - unplanned mode loses writes not yet replicated; prefer planned whenever the source is
    healthy
Nothing was executed.
(exit 0)
```

3. **Execute.** The fence step is recorded as **skipped**, because
   us-east-1's EKS API doesn't answer. The region is marked fenced anyway.

```text
$ PYTHONPATH=src python3 -m failover --fake-world outage.json execute --mode unplanned --confirm dr-app-global --target us-west-2
Run 20261014T071744Z-unplanned-us-west-2: unplanned failover us-east-1 -> us-west-2
[1/6] precheck        done: us-west-2 healthy, us-east-1 unreachable (connect timeout), writer us-east-1, last known lag 1.2s (potential data loss)
[2/6] fence-source    skipped: us-east-1 EKS API unreachable (us-east-1: EKS API endpoint timed out); workers NOT confirmed at 0. us-east-1 marked fenced: scale its workers to 0 before it rejoins (runbooks/unplanned-failover.md, 'Fence later')
[3/6] promote-target  done: dr-app-us-west-2 detached from dr-app-global and promoted; RPO exposure was 1.2s; epoch 1
[4/6] scale-target    done: us-west-2: API min replicas 3, workers 2
[5/6] flip-dns        done: us-west-2 is PRIMARY, us-east-1 is SECONDARY
[6/6] postcheck       done: us-west-2 healthy, writer, PRIMARY, 2 workers; us-east-1 unreachable: its workers are unverified
Completed: us-west-2 is the writer (epoch 1); us-east-1 is fenced
(exit 0)
```

4. **Verify.** The warnings are expected and stay until failback: the old
   writer is fenced, but its workers were never confirmed at 0, and its
   cluster would still accept writes if the region came back.

```text
$ PYTHONPATH=src python3 -m failover --fake-world outage.json status
Global cluster dr-app-global  record orders.example.com
Aurora global writer: us-east-1   writers now: us-east-1, us-west-2   DNS PRIMARY: us-west-2   state: writer us-west-2, epoch 1

REGION      DEPLOYED AS  HEALTH       AURORA              LAG     DNS        WORKERS  API MIN  FENCED
us-east-1   primary      unreachable  writer (global)     -       SECONDARY  -        -        yes
us-west-2   dr           healthy      writer (detached)   -       PRIMARY    2        3        no

Warnings:
  ! us-east-1 is fenced but its workers were never confirmed at 0 (unreachable)
  ! us-east-1 is fenced but its cluster still accepts writes: rebuild it as a secondary before it rejoins (runbooks/failback.md)
(exit 0)
```

5. **Secrets.** If you need to rotate the database password while
   us-east-1 is down, promote the replica secret first
   (`aws secretsmanager stop-replication-to-replica --secret-id dr-app/aurora-master --region us-west-2`).

## Fence later

When us-east-1 starts coming back, **before** anything there reaches its
database:

1. Scale its workers to 0:
   `helm upgrade dr-app helm/dr-app --kube-context <us-east-1> -n orders --reuse-values --set workers.enabled=false`.
2. Scale its API to 0 or delete its Ingress, so the ALB stops serving from
   a stale database: `kubectl --context <us-east-1> -n orders scale deploy dr-app-api --replicas=0`
   (after deleting the HPA or pausing it).
3. Confirm that `status` no longer shows workers in us-east-1.
4. Do not let anything write to the old us-east-1 cluster. Export the
   writes that never replicated for reconciliation
   ([failback.md](failback.md), step 1).

## If a step fails

- Re-run the same `execute` command. It resumes at the failed step.
- **Detach failed:** check the DR cluster with
  `aws rds describe-db-clusters --region us-west-2`. If it is already
  standalone and available, the resumed step records "already detached".
- **DNS step failed** because Route 53's control plane, which lives in
  us-east-1, is impaired: traffic is already on us-west-2 because the
  us-east-1 health check is failing. Keep retrying the run. Until it
  succeeds, the risk is traffic returning to us-east-1 when its health
  check recovers, which is why "Fence later" step 2 matters.
- **Scale-up is slow** because EC2 capacity is short: raise the node
  group's max, try other instance types, and accept degraded throughput.
  Don't stop the run halfway.
