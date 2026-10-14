# Operations

> This stack has been validated with `terraform validate` only and never
> deployed by the author. The steps below are how it is meant to be operated:
> treat them as a runbook to rehearse in a sandbox account, not a record of
> production use. CLI flags are from the AWS CLI v2 documentation; check them
> against your CLI version before an incident, not during one.

## Deploy

```bash
cd terraform/examples/basic
cp terraform.tfvars.example terraform.tfvars    # regions, break-glass role, emails
python3 ../../../scripts/check_plan_policy.py ../../../policy/backup-policy.json
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

- The validator zip is built by `archive_file` from `src/restore_validator`
  into `.build/` (git-ignored). boto3 comes from the Lambda runtime.
- Email subscribers must confirm the SNS subscription in each region.
- The vault lock starts in **governance** mode. Don't change `vault_lock.mode`
  in the policy file without reading [ADR 0002](decisions/0002-governance-vs-compliance-lock.md).
- `rds_test_subnet_group` must exist in the DR region and must have no route
  to production: restored test databases come up there.

## Onboarding a resource

1. Tag it: `backup-policy = gold` (copied to DR on every rule, 35 days of
   PITR where supported) or `silver` (weekly copies only). To opt a resource
   out despite an inherited tag, add `backup-exclude = true`.
2. Make sure the resource's KMS key lets the backup role use it. For a
   customer managed key, add the role from the `backup_role_arn` output to
   the key policy. This is the most common first-backup failure (the sample
   data's `sessions-table` fails this way).
3. Wait for the next scheduled window, or start an on-demand job to prove it:

   ```bash
   aws backup start-backup-job --backup-vault-name backup-dr-demo-primary \
     --resource-arn <arn> --iam-role-arn <backup_role_arn>
   ```

4. Check that the copy landed:
   `aws backup list-copy-jobs --by-resource-arn <arn> --region us-east-1`.
5. Add the resource to the inventory the RPO/RTO report reads (name, type,
   tier). For gold, confirm the type has a restore-testing selection
   (`restore_testing.selections`). If not, add one, or accept that its RTO
   is unproven and record that.

New tier or retention: edit `policy/backup-policy.json`, run
`check_plan_policy.py`, open a PR. CI runs the checker and `terraform validate`.

## Manual restore in the DR region

Use this for a real regional event or a DR exercise. Work in the DR region
(`--region us-west-2`) against the DR vault.

### Find the recovery point

```bash
aws backup list-recovery-points-by-backup-vault --region us-west-2 \
  --backup-vault-name backup-dr-demo-dr \
  --by-resource-arn arn:aws:rds:us-east-1:123456789012:db:orders-db \
  --query 'RecoveryPoints[?Status==`COMPLETED`] | sort_by(@,&CreationDate)[-1]'
```

The resource ARN is the *original* (primary-region) ARN. Copies keep it.

### RDS

```bash
aws backup get-recovery-point-restore-metadata --region us-west-2 \
  --backup-vault-name backup-dr-demo-dr --recovery-point-arn <rp-arn> > meta.json
# edit meta.json: DBInstanceIdentifier (new name), DBSubnetGroupName,
# VpcSecurityGroupIds, MultiAZ, and keep KmsKeyId = the DR key
aws backup start-restore-job --region us-west-2 \
  --recovery-point-arn <rp-arn> --iam-role-arn <restore_testing_role_arn> \
  --resource-type RDS --metadata file://meta.json
aws backup describe-restore-job --region us-west-2 --restore-job-id <id>
```

Then:

1. Wait for `available`, connect from a bastion in the DR VPC and run the
   application's smoke queries (row counts on key tables, latest
   `updated_at`, which gives you the actual data loss).
2. Point the application at the new endpoint (Route 53 record or secret
   rotation). Restores always create a new instance, never overwrite.
3. Record the restore duration: it's your measured RTO.

For point-in-time restore of a continuous recovery point, add
`RestoreTime` (ISO 8601) to the metadata. The continuous point only exists
in the primary region. Cross-region copies are snapshots, so the DR region's
best RPO is the last copied snapshot.

### DynamoDB

```bash
aws backup get-recovery-point-restore-metadata --region us-west-2 \
  --backup-vault-name backup-dr-demo-dr --recovery-point-arn <rp-arn>
aws backup start-restore-job --region us-west-2 \
  --recovery-point-arn <rp-arn> --iam-role-arn <restore_testing_role_arn> \
  --resource-type DynamoDB \
  --metadata '{"targetTableName":"sessions-dr","encryptionType":"KMS","kmsMasterKeyArn":"<dr key arn>"}'
```

Then check the item count with a `Scan` using `Select=COUNT` (not
`DescribeTable.ItemCount`, which lags by hours), re-create any streams,
TTL, auto scaling and global-table settings (a restore doesn't bring them
back), and switch the application's table name.

## On COPY_JOB_FAILED

The topic receives the vault event and the EventBridge rule's full event.
Within the business day:

1. **Read the status message:**
   `aws backup describe-copy-job --copy-job-id <id> --region us-east-1`.
2. **Triage by message:**

   | Message contains | Usual cause | Fix |
   |---|---|---|
   | `Insufficient privileges` / `kms` | DR key policy doesn't allow the backup role (or, cross-account, the source account) | Fix the key policy in Terraform. Never fix it by hand in the console |
   | `Access denied` on the vault | DR vault policy missing `CopyIntoBackupVault` (cross-account) or Organizations cross-account backup off | Enable in Organizations, re-apply |
   | `retention` / `lock` | Copy lifecycle outside the DR vault lock range | `check_plan_policy.py` BKP-006 should have caught it. Fix the policy file |
   | Quota / throttling | Too many concurrent copies | Spread rule start times, or ask for a quota increase |

3. **Re-run the copy** for the newest recovery point once fixed:

   ```bash
   aws backup start-copy-job --region us-east-1 \
     --recovery-point-arn <primary rp-arn> --source-backup-vault-name backup-dr-demo-primary \
     --destination-backup-vault-arn <dr vault arn> --iam-role-arn <backup_role_arn> \
     --lifecycle DeleteAfterDays=35
   ```

4. **Measure exposure:** run `scripts/rpo_rto_report.py` on a fresh export.
   The "DR copy age" column is the data loss you'd take if the primary
   region went down right now.

A gold resource whose DR copy is older than its RPO is an incident, even
while primary backups succeed.

## How Vault Lock behaves

| | Governance (default) | Compliance |
|---|---|---|
| Recovery point deleted before min retention | Rejected | Rejected |
| Retention outside [min, max] at backup/copy time | Job fails | Job fails |
| Lock removed | By a principal with `backup:DeleteBackupVaultLockConfiguration` | Only during the grace period (`changeable_for_days`, minimum 3) |
| After the grace period | Same as before | **Immutable.** Nobody, including root and AWS Support, can remove it or delete the vault until all points expire |
| Lifecycle shortened below min | Rejected | Rejected |

- The lock and the vault access policy are separate layers. The lock caps
  retention changes even for the break-glass role. The access policy decides
  who may try at all.
- Changing the lock min or max doesn't touch existing recovery points.
- In governance mode, `DeleteBackupVaultLockConfiguration` must be denied by
  SCP to everyone except break-glass, or the lock is only a speed bump.

## Break-glass deletion

Use this for a legal deletion request, or a recovery point containing data
that must not exist. Never use it to save money.

1. Open a ticket with the reason, the recovery point ARNs and an approver
   (two people, one from security).
2. Assume the break-glass role (`break_glass_role_arn`). Assuming it should
   page the security channel: a CloudTrail `AssumeRole` alert on that role
   ARN is a prerequisite outside this module.
3. Delete:
   `aws backup delete-recovery-point --backup-vault-name <vault> --recovery-point-arn <arn>`.
   A point still inside the vault lock's minimum retention can't be deleted
   by anyone. In compliance mode, that includes break-glass. That's intended.
4. Note that the copy in the other region is a separate recovery point.
   Delete both, or neither.
5. Attach the CloudTrail events to the ticket and close it.

## Quarterly DR exercise

Goal: prove the RPO and RTO for every gold service from the DR region, with
the numbers written down.

1. **Plan (week before):** pick the services, book the people, announce the
   window. Export job history:

   ```bash
   for r in us-east-1 us-west-2; do
     aws backup list-backup-jobs --region $r --by-created-after <90 days ago>
     aws backup list-copy-jobs --region $r --by-created-after <90 days ago>
     aws backup list-restore-jobs --region $r --by-created-after <90 days ago>
   done
   ```

   Assemble them with a resource inventory into the `sample-data/jobs.json`
   shape and run `rpo_rto_report.py`. Every gold row should be OK before you
   start.
2. **Restore** each gold resource from the **DR vault** into an isolated DR
   VPC using the runbooks above, with the clock running.
3. **Validate** with the application's own checks, not just "it came up":
   log in, read recent records, run one write path against a scratch copy.
4. **Record** per service: recovery point age (actual RPO), wall-clock time
   to a working service (actual RTO), and every manual step that wasn't in
   the runbook.
5. **Clean up** the restored resources (they aren't restore-testing
   resources, so nothing deletes them automatically).
6. **Review:** an RTO miss becomes a ticket (larger instance class, a
   pre-provisioned subnet group, a scripted DNS switch). A runbook gap
   becomes a PR to this file.

## Reading the restore-testing results

```bash
aws backup list-restore-jobs --region us-west-2 \
  --by-restore-testing-plan-arn <restore_testing_plan_arn> \
  --query 'RestoreJobs[].[CreationDate,ResourceType,Status,ValidationStatus,ValidationStatusMessage]'
```

Logs Insights on `/aws/lambda/backup-dr-demo-restore-validator`:

```text
fields @timestamp, resource_type, validation_status, checks.0, checks.1
| filter message like /restore validation/
| sort @timestamp desc
```

A FAILED verdict raises `backup-dr-demo-restore-validation-failed-<type>`.
Treat it like a failed backup: the copy exists but you can't prove it
restores.
