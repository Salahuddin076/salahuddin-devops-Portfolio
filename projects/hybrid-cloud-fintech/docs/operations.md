# Operations

> Validated with `terraform validate`, `ansible-lint`/`--syntax-check`, and
> `python3 -m unittest` only -- never applied or run against a real
> account, VMware environment, or host. The runbook below is how this
> design is meant to be operated; the "restore-test results" table is
> synthetic evidence of the *shape* of record-keeping this project expects,
> not a report from a real incident or exercise.

## Deploying the connectivity and segmentation layer (if this were real)

```bash
cd terraform/examples/reference
cp terraform.tfvars.example terraform.tfvars   # replace on_prem_gateways with real IPs
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

After apply, the on-prem side must independently configure its two edge
devices (the Customer Gateways' real-world counterparts) with the
pre-shared keys / certificates AWS returns for each of the 4 tunnels, and
bring up BGP sessions (or static routes, if `static_routes_only = true`)
to the ASN each `aws_customer_gateway` declares.

## Applying the Ansible baseline (if this were real)

```bash
cd ansible
ansible-playbook -i inventory/hosts.ini site.yml --check   # dry run first, always
ansible-playbook -i inventory/hosts.ini site.yml --limit aws_hosts
ansible-playbook -i inventory/hosts.ini site.yml --limit onprem_hosts
```

This project never runs the real command above -- see the README's
validation section for what was actually executed (`--syntax-check` and
`ansible-lint` against the synthetic inventory in `inventory/hosts.ini`).

## DR runbook: database replication and the on-prem systems of record

This is deliberately not "a backup cron job plus a cross your fingers." It
is a restore-test procedure with a result that a reviewer -- or an auditor,
for the PCI-DSS angle this project's evidence plays into -- can read
without re-running anything.

### Scope

- The **regulated-zone RDS replica** on the AWS side (reference only --
  the actual RDS Terraform lives in `../aws-landing-zone` /
  `../aws-multi-region-eks-dr`, not duplicated here).
- The **on-prem systems of record** this replica tracks, reachable only
  through `module.connectivity`'s VPN link.

### Procedure

1. **Trigger**: scheduled monthly, or on-demand before a change to the
   connectivity or segmentation Terraform (prove the restore path still
   works before changing the network it depends on).
2. **Isolate**: restore into an isolated subnet/VPC that has no route back
   to the regulated zone's production security group -- the restored
   instance must never be reachable from, or able to reach, production.
3. **Restore**: bring up the database from the most recent verified backup
   (RDS automated snapshot or on-prem backup export, depending which side
   is being tested this cycle).
4. **Validate data**: run the smoke-check query set (row counts on the
   ledger and account tables, latest `updated_at` timestamp vs the backup's
   creation time -- the gap is the measured data loss / RPO for that test).
5. **Validate reachability**: confirm the restored instance is NOT
   reachable from the edge zone's security group (a restore that's
   reachable from production is a finding, not a pass) and IS reachable
   from the isolated test subnet used to run step 4.
6. **Record**: append a row to the table below (synthetic, below) with
   date, RPO achieved, RTO achieved, and pass/fail per check. A `FAIL` on
   any row blocks the next planned change to `terraform/modules/connectivity`
   or `terraform/modules/segmentation` until re-tested.
7. **Tear down**: destroy the restored instance and its isolated subnet.
   Nothing from a restore test is left running.

### Restore-test results (synthetic, illustrative of the evidence format)

| Date | Target | Backup age at restore | Measured RPO | Measured RTO | Data integrity check | Network isolation check | Result |
|---|---|---|---|---|---|---|---|
| 2026-07-06 | Regulated-zone RDS replica | 3h12m | 3h12m (target: 4h) | 0h41m (target: 1h) | PASS (row counts match source as of backup time) | PASS (unreachable from edge SG, reachable from isolated test subnet) | PASS |
| 2026-08-03 | On-prem ledger export | 22h50m | 22h50m (target: 24h) | 2h05m (target: 4h) | PASS | PASS | PASS |
| 2026-09-07 | Regulated-zone RDS replica | 3h40m | 3h40m (target: 4h) | 0h58m (target: 1h) | **FAIL** -- `account_balances` row count 3 rows short of source; traced to a replication lag spike during the backup window, not data loss. Re-tested 2026-09-08, PASS. | PASS | FAIL -> PASS on retest |
| 2026-10-05 | On-prem ledger export | 20h15m | 20h15m (target: 24h) | 1h50m (target: 4h) | PASS | PASS | PASS |

Reading this the way `../aws-backup-cross-region-dr`'s RPO/RTO report
reads its own history: the single `FAIL` row is the point of the whole
exercise. A restore that "basically worked" except for a 3-row drift during
a replication lag spike is exactly the kind of gap a restore test is
supposed to surface before an incident does, and the same row shows it was
followed up (retested the next day, passed) rather than quietly dropped.

### Incident response: link impaired, not restoring from backup

This is the common case this project's graceful-degradation pattern is
for -- the link is flapping or down, but nothing has been lost; see
`docs/architecture.md`'s sequence diagram and `src/degrade/`.

1. Confirm via the VPN connection's tunnel status (both tunnels on both
   connections DOWN is the actual full-outage case; one tunnel down on one
   connection is expected transient behavior and does not page anyone).
2. Confirm edge services are returning `202 Accepted` (queued) rather than
   `5xx` for on-prem-dependent operations -- that's the degrade path
   working, not a new incident.
3. Once the link recovers, run `replay_pending` (via the scheduled job
   described in `src/degrade/replay.py`'s module docstring) and confirm the
   outbox drains to zero pending entries.
4. If any entries moved to `failed` (exhausted `max_attempts`), those are a
   genuine incident follow-up: each one is a customer-facing request that
   needs manual reconciliation, not a silent write-off.

### Capacity planning for 24x7 workloads

- EKS node groups and RDS instance classes are sized and reviewed in
  `../aws-multi-region-eks-dr` (not duplicated here); this project's
  concern is that a link outage must not create a capacity problem on the
  AWS side -- `DegradingClient` keeps accepting requests at normal
  throughput by design, deferring only the on-prem-dependent half of the
  work, so a link outage degrades a subset of functionality rather than
  the whole service's capacity.
- The outbox itself needs capacity planning past a single instance: see
  "Where this stops short of a production build" in `docs/architecture.md`.

### AWS resource lifecycle hygiene

Rightsizing, AMI lifecycle, snapshot/volume cleanup for the EKS/RDS layer
are `../finops-cost-optimization`'s and `../aws-backup-cross-region-dr`'s
scope, not duplicated here; this project's own AWS footprint (VPN
connections, customer/virtual private gateways, security groups, NACLs) has
no snapshots or AMIs to clean up -- the only ongoing hygiene is removing
`on_prem_gateways` entries for decommissioned on-prem devices and the
`allowed_ingress`/`allowed_egress` entries for flows that are no longer
needed, both of which `tests/test_terraform_static.py` would need updating
alongside.
