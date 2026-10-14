# Runbook: failback (us-west-2 -> us-east-1)

> Reference runbook, rehearsed only against the CLI's fake adapters. The
> outputs below are real output of those fakes. Durations are **targets to
> measure**.

Failback is a planned failover in the other direction, with one extra
precondition: the region you return to was fenced, so its database must
be a healthy secondary of the current writer. The CLI refuses a failback
without `--rebuild-confirmed`, and the pre-check verifies membership even
with it.

## When to fail back, and when not

- Fail back when us-east-1 has been stable for an agreed period (24 hours
  is a reasonable default), at a low-traffic time, with the same people
  in the room as for a planned failover.
- **Don't rush it.** Running in us-west-2 is a supported state. A second
  write interruption in one day to get "home" sooner is rarely worth it.
- Don't fail back while S3 replication from us-west-2 to us-east-1 still
  has a backlog.

## Who decides

The service owner proposes it and the incident commander (or change
manager) approves, as a normal change, not as part of the incident.

## Expected durations (targets to measure)

| Phase | Target to measure |
|---|---|
| Rebuild us-east-1 as a secondary (after an unplanned failover) | hours: a new secondary cluster must sync the whole volume |
| Failback switchover | same as a planned failover |

## 1. After an unplanned failover: rebuild first

The old us-east-1 cluster left the topology as a standalone writer, and
it may hold writes that never replicated.

1. **Reconcile.** Before deleting it, export what it has and us-west-2
   doesn't. At minimum, compare orders created after the last replicated
   transaction. The data owner decides what to replay and what to
   discard. Record the decision in the incident.
2. **Delete the old cluster** (disable deletion protection; take a final
   snapshot and keep it).
3. **Rebuild the topology from us-west-2.** Create the global cluster from
   the current writer and add us-east-1 as a secondary. Reusing the same
   global cluster ID keeps the confirm token and the config unchanged.
   ```bash
   aws rds delete-global-cluster --global-cluster-identifier dr-app-global   # the empty old one
   aws rds create-global-cluster --global-cluster-identifier dr-app-global \
     --source-db-cluster-identifier arn:aws:rds:us-west-2:123456789012:cluster:dr-app-us-west-2
   ```
   Then let Terraform create the us-east-1 secondary: in
   `environments/global`, move state so that `aws_rds_cluster.primary`
   refers to us-west-2 and the module creates the other region as the
   secondary, or `terraform state rm` the old us-east-1 cluster and
   instances and import the rebuilt ones. Plan carefully, with deletion
   protection on. This is the step most likely to go wrong, so rehearse
   it in a sandbox before you need it.
4. **Wait for the new secondary to sync**, and for its lag to settle
   below the threshold.
5. **Bring the us-east-1 app back as a standby:** API at standby size,
   `workers.enabled=false`, and the deep health check passing.

## 2. After a planned failover: nothing to rebuild

The switchover kept us-east-1 in the global cluster as a secondary.
Check `status`: us-east-1 shows `secondary (global)` with low lag.

## 3. Fail back

This example follows a planned failover drill (world file `drill.json`).

```text
$ PYTHONPATH=src python3 -m failover --fake-world drill.json execute --mode planned --confirm dr-app-global --target us-west-2
Run 20261014T071744Z-planned-us-west-2: planned failover us-east-1 -> us-west-2
[1/6] precheck        done: us-west-2 healthy, us-east-1 healthy, writer us-east-1, lag 0.4s < 5s
[2/6] fence-source    done: workers in us-east-1 scaled to 0; us-east-1 marked fenced
[3/6] promote-target  done: managed switchover complete: dr-app-us-west-2 is the global writer; epoch 1
[4/6] scale-target    done: us-west-2: API min replicas 3, workers 2
[5/6] flip-dns        done: us-west-2 is PRIMARY, us-east-1 is SECONDARY
[6/6] postcheck       done: us-west-2 healthy, writer, PRIMARY, 2 workers
Completed: us-west-2 is the writer (epoch 1); us-east-1 is fenced
(exit 0)
```

Without the flag, the CLI refuses:

```text
$ PYTHONPATH=src python3 -m failover --fake-world drill.json execute --mode planned --confirm dr-app-global --target us-east-1
error: failback refused: us-east-1 is fenced. Confirm its database is a healthy secondary of us-west-2 (after a planned switchover it already is; after an unplanned failover it must be rebuilt, runbooks/failback.md), then re-run with --rebuild-confirmed
(exit 3)
```

Read the plan. It is a failback, and the notes say so:

```text
$ PYTHONPATH=src python3 -m failover --fake-world drill.json plan --mode planned --target us-east-1
Plan: planned failback us-west-2 -> us-east-1  (global cluster dr-app-global)
  1. precheck        us-east-1 deep health OK; us-west-2 healthy (planned needs both); Aurora
                     global writer is us-west-2 and us-east-1 is a member; replication lag into
                     us-east-1 < 5s; failback: us-east-1 must be a secondary again
                     (--rebuild-confirmed given)
  2. fence-source    scale workers to 0 in us-west-2 (helm: workers.enabled=false); mark
                     us-west-2 fenced in the state file. Must succeed in planned mode
  3. promote-target  failover-global-cluster --switchover to dr-app-us-east-1 (managed
                     switchover: waits for replication to catch up, no data loss; us-west-2
                     becomes a secondary)
  4. scale-target    us-east-1: HPA minReplicas 3, workers.enabled=true, workers.replicas=2
  5. flip-dns        Route 53 orders.example.com: us-east-1 -> PRIMARY, us-west-2 -> SECONDARY
                     (one change batch)
  6. postcheck       us-east-1 healthy, a writer, PRIMARY in DNS, workers > 0; no unfenced second
                     writer; workers 0 in us-west-2 if reachable
Notes:
  - execute needs: --confirm dr-app-global
  - us-east-1 is fenced in the state file: this is a failback and needs --rebuild-confirmed
Nothing was executed.
(exit 0)
```

Confirm that us-east-1 is a secondary with low lag, then run it:

```text
$ PYTHONPATH=src python3 -m failover --fake-world drill.json execute --mode planned --confirm dr-app-global --target us-east-1 --rebuild-confirmed
Run 20261014T071744Z-planned-us-east-1: planned failback us-west-2 -> us-east-1
[1/6] precheck        done: us-east-1 healthy, us-west-2 healthy, writer us-west-2, lag 0.0s < 5s
[2/6] fence-source    done: workers in us-west-2 scaled to 0; us-west-2 marked fenced
[3/6] promote-target  done: managed switchover complete: dr-app-us-east-1 is the global writer; epoch 2
[4/6] scale-target    done: us-east-1: API min replicas 3, workers 2
[5/6] flip-dns        done: us-east-1 is PRIMARY, us-west-2 is SECONDARY
[6/6] postcheck       done: us-east-1 healthy, writer, PRIMARY, 2 workers
Completed: us-east-1 is the writer (epoch 2); us-west-2 is fenced
(exit 0)
```

```text
$ PYTHONPATH=src python3 -m failover --fake-world drill.json status
Global cluster dr-app-global  record orders.example.com
Aurora global writer: us-east-1   writers now: us-east-1   DNS PRIMARY: us-east-1   state: writer us-east-1, epoch 2

REGION      DEPLOYED AS  HEALTH       AURORA              LAG     DNS        WORKERS  API MIN  FENCED
us-east-1   primary      healthy      writer (global)     -       PRIMARY    2        3        no
us-west-2   dr           healthy      secondary (global)  0.0s    SECONDARY  0        3        yes

Warnings: none
(exit 0)
```

us-west-2 is now the fenced standby, as it was before the drill. Its
API minimum stays at 3 until you lower it: set it back to the standby
size from `values-dr.yaml` with a normal `helm upgrade`.

## Afterwards

- Make sure `environments/global` plans cleanly. After an unplanned cycle,
  any remaining drift is from the rebuild in step 1.
- Review the audit log for both runs together. The run IDs link the
  lines.
