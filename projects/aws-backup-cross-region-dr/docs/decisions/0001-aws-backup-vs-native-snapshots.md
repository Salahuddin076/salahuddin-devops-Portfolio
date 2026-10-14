# ADR 0001: AWS Backup plans instead of per-service native snapshots

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-backup-cross-region-dr (portfolio implementation)

## Context

The estate has RDS, DynamoDB, S3 and EBS, and is expected to grow. Every
one of them has a native backup feature: RDS automated backups and manual
snapshots, DynamoDB PITR and on-demand backups, S3 versioning and
replication, EBS snapshots with Data Lifecycle Manager. Each one can also
be copied cross-region in its own way.

Requirements:

- One retention policy per tier (gold, silver), applied the same way to
  every resource type.
- A copy in a second region (optionally a second account) for gold.
- Immutability that an administrator in the workload account can't bypass.
- Restore tests with recorded results.
- One place to see whether everything is protected.

## Decision

Use **AWS Backup** for all four types: one plan per tier, selection by tag,
`copy_action` to a DR vault, Vault Lock, restore testing and Audit Manager.
Native features stay only where AWS Backup builds on them (RDS and S3
continuous backup is AWS Backup managing PITR).

## Consequences

Good:

- **One policy, many types.** A rule is written once and applies to every
  tagged resource. The policy file, the CI check and the RPO report all
  speak the same vocabulary.
- **Tag-based onboarding.** A new resource is protected by a tag, not by a
  new snapshot schedule, Lambda or DLM policy per service.
- **Immutability exists at all.** Vault Lock and vault access policies apply
  to every recovery point in the vault. Native RDS and EBS snapshots can be
  deleted by anyone with the API permission. S3 Object Lock covers S3 only.
- **Cross-region and cross-account copy is one block** (`copy_action`)
  instead of per-service copy code, with the destination key re-encrypting
  the copy.
- **Native restore testing and audit evidence** come with it.

Accepted costs:

- **Feature lag per service.** Some native options aren't exposed, or arrive
  later (for example some engine-specific snapshot settings). S3 backup
  needs versioning and has its own limits on bucket size and object counts.
- **The cross-region copy is a snapshot.** PITR (continuous backup) stays
  in the source region, so the DR region's RPO is the last copied snapshot,
  not seconds. A tighter regional RPO needs replication (Aurora Global
  Database, DynamoDB global tables, S3 CRR) *in addition*, and replication
  is not a backup: it faithfully replicates deletions and ransomware too.
- **Pricing** per GB can be higher than raw snapshots for some types. See
  [cost](../cost.md).
- **Another IAM surface:** the service role and key policies must allow
  AWS Backup on every customer managed key. A missing grant is the most
  common failure (sample data: `sessions-table`).

## Alternatives considered

- **Native snapshots plus scheduled Lambdas to copy them.** That means
  four mechanisms, four retention implementations and no immutability for
  RDS and EBS. Rejected.
- **Data Lifecycle Manager for EBS, RDS automated backups, DynamoDB PITR.**
  Fine per service, but there's no single policy, no vault lock, and no
  common restore-testing or audit story.
- **Third-party backup products.** They're capable, and they add licensing,
  agents or appliances, and a second control plane. Not justified for an
  all-AWS estate.
