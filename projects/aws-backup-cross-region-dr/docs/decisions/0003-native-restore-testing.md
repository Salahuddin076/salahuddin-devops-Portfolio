# ADR 0003: AWS Backup native restore testing, plus a small validator Lambda

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-backup-cross-region-dr (portfolio implementation)

## Context

A backup that has never been restored is a hope, not a recovery plan.
Restore tests usually fail organisationally rather than technically: they're
manual, run once a year, leave restored resources running (expensive, and a
copy of production data nobody is watching), and record their results in a
wiki page.

We need restores that happen on a schedule, prove something about the
restored data, clean up after themselves, and leave a record an auditor
and the RPO/RTO report can read.

## Decision

1. **Use AWS Backup restore testing** (`aws_backup_restore_testing_plan` and
   `aws_backup_restore_testing_selection`) in the DR region, against the
   **DR vault**: weekly, latest recovery point within 7 days, one selection
   per resource type, tag-scoped to the tier.
2. **Validate with a small Lambda** (`src/restore_validator`) triggered by
   `Restore Job State Change` = `COMPLETED`. It checks restore-testing jobs
   only, runs a type-specific check, and reports with
   `PutRestoreValidationResult`, so the verdict lives on the restore job in
   AWS Backup itself.
3. **Cleanup belongs to AWS Backup.** Restore testing deletes the restored
   resource after `validation_window_hours`. The Lambda's optional early
   cleanup is off by default and refuses untagged resources, in code and in IAM.
4. **Metrics through EMF.** One log line per verdict becomes
   `RestoreValidationSucceeded` (1/0 by `ResourceType`), with an alarm per
   tested type.

The checks are deliberately cheap. They prove the restore produced a usable
resource with data in it. They don't prove application correctness:

| Type | Check |
|---|---|
| RDS | Instance `available`, endpoint accepts TCP, optional row-count query (stubbed until a driver layer is added) |
| DynamoDB | `Scan` with `Select=COUNT` reaches a minimum item count (`DescribeTable.ItemCount` lags by hours, so it isn't used) |
| S3 | Object count reaches a minimum, and a sample of objects matches its stored SHA-256 (or MD5 ETag) |
| EBS | Volume `available` |

## Consequences

Good:

- **Scheduled, scoped and self-cleaning** without writing an orchestrator.
- **Tests the copy that matters.** A DR-vault restore exercises the copy
  job, the DR key policy and the DR vault, which is exactly what a regional
  failover depends on.
- **Results are first-class data.** `ValidationStatus` is on each restore
  job, so `list-restore-jobs` (and `rpo_rto_report.py`) can compute pass
  rates and measured restore durations against RTO.
- **Testable code.** The Lambda is standard-library Python with injected
  adapters, so every resource type, verdict and refusal is unit-tested
  without AWS.

Accepted costs:

- **Restore-test compute is billed** while resources exist. That's kept down
  with short windows and small instance classes ([cost](../cost.md)).
- **The RDS row count is a stub** until a database driver (pg8000, PyMySQL)
  and credentials from Secrets Manager are added. The validator says
  "row count skipped" rather than claiming a pass it didn't check. The TCP
  check needs the Lambda in the DR VPC (`restore_validator.subnet_ids`).
- **Not verified live:** the restore-testing behaviour against cross-region
  copies selected by tag conditions, the exact tag AWS applies to restored
  test resources, and the `Restore Job State Change` event's full field
  set. The handler re-reads the job with `DescribeRestoreJob` instead of
  trusting event fields for exactly that reason.
- **Restore duration in a test isn't the full RTO.** It leaves out DNS
  switchover, application configuration and people. The quarterly exercise
  in [operations](../operations.md#quarterly-dr-exercise) measures the rest.

## Alternatives considered

- **Step Functions orchestrating `StartRestoreJob`, checks and deletes.**
  Full control, and a lot of state machine to own, including cleanup on
  every failure path. Native restore testing already does the scheduling
  and the deletion.
- **Manual quarterly restores only.** Still done (the DR exercise), but too
  rare to catch a broken key policy or copy job within the RPO.
- **Trusting `RESTORE_JOB_COMPLETED` as success.** "The restore API
  finished" isn't "the data is there". An empty table or a database stuck in
  `incompatible-restore` both complete.
