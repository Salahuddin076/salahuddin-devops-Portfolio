# Security

> Design intent, validated with `terraform validate` only. Policies have not
> been exercised against a live account; IAM Access Analyzer and a sandbox
> apply are the next steps before trusting them.

## Threat model: ransomware and the malicious insider

The attacker this design assumes has **administrator credentials in the
primary workload account**. That might be a phished SSO session, a leaked
CI key or a compromised admin laptop. Their goal is to make recovery
impossible before they encrypt or delete production data. With admin
rights, the usual sequence is:

| Attacker step | Control in this design | Residual risk |
|---|---|---|
| Delete recovery points | Vault access policy denies `DeleteRecoveryPoint` to every principal except the break-glass role. Vault Lock rejects deletion before minimum retention, even for break-glass | In governance mode, an admin who can remove the lock and edit the vault policy can undo both. Deny those actions by SCP (below) |
| Shorten retention so points expire tonight | `UpdateRecoveryPointLifecycle` denied by the same policy. Vault Lock min retention. `RECOVERY_POINT_MODIFIED` vault notification | Same as above |
| Delete the vault | A vault with recovery points can't be deleted. Compliance lock makes this permanent | |
| Schedule deletion of the KMS key (points become unreadable) | Separate CMK per vault, so the DR key is unaffected by the primary. 30-day deletion window. Alert on `ScheduleKeyDeletion` (CloudTrail, outside this module) | Single-account: the admin can schedule both. Cross-account removes this |
| Stop backups (delete plan or selection, untag resources) | Job-failure alarms don't fire for jobs that never start. The RPO report and the Audit Manager frequency control do | Detection, not prevention: hours to a day |
| Delete the DR copies too | Cross-account DR vault: primary-account admin has no rights in the recovery account | Only with the optional cross-account mode |

### Immutability

- **Vault Lock** on both vaults: min 7, max 400 days (from the policy file).
  Every rule's retention is checked to sit inside that range (BKP-006, plus
  a Terraform validation), because a retention outside the range makes the
  backup job fail, not the lock.
- **Governance mode by default.** It stops accidents and casual deletion, and
  can be removed by a principal with `backup:DeleteBackupVaultLockConfiguration`.
  **Compliance mode** turns that off for good once the grace period ends.
  The trade-off is in [ADR 0002](decisions/0002-governance-vs-compliance-lock.md).
- **Governance needs an SCP to mean much.** Recommended organisation SCP,
  attached to workload OUs (not in this module, which deploys into one
  account; see the landing-zone project for the SCP pattern):

  ```json
  {
    "Effect": "Deny",
    "Action": [
      "backup:DeleteBackupVaultLockConfiguration",
      "backup:PutBackupVaultAccessPolicy",
      "backup:DeleteBackupVaultAccessPolicy",
      "backup:DeleteRecoveryPoint",
      "backup:UpdateRecoveryPointLifecycle",
      "kms:ScheduleKeyDeletion",
      "kms:PutKeyPolicy"
    ],
    "Resource": "*",
    "Condition": {
      "ArnNotLike": { "aws:PrincipalArn": [
        "arn:aws:iam::*:role/backup-break-glass",
        "arn:aws:iam::*:role/terraform-deployer"
      ] }
    }
  }
  ```

### Separate keys

Four CMKs, all with rotation enabled:

| Key | Region | Used by |
|---|---|---|
| Primary vault key | primary | Backup role (backup, restore), via grants for AWS resources |
| DR vault key | DR | Backup role (copy re-encryption), restore-testing role, validator (Decrypt, via S3 and DynamoDB only) |
| Primary notification key | primary | `backup`, `events`, `cloudwatch` services, scoped to the account |
| DR notification key | DR | same |

A copy is **re-encrypted with the destination vault's key**, so the DR key
alone is enough to restore in DR. Disabling, deleting or losing access to
the primary key (or the whole primary region) doesn't affect the DR copies.
Grants are restricted with `kms:GrantIsForAWSResource`, so the role can't
mint grants for arbitrary principals.

### Optional cross-account vault

Point the `aws.dr` provider at a role in a dedicated recovery account (an
`assume_role` block in `examples/basic/providers.tf`). The module detects
the different account ID and:

- adds `backup:CopyIntoBackupVault` for the primary account to the DR vault
  policy;
- adds a key-policy statement on the DR key for the primary account,
  restricted with `kms:ViaService = backup.<dr-region>.amazonaws.com`;
- creates the restore-testing role and the validator in the recovery
  account, so no role trusts across accounts.

Also required, outside this module: cross-account backup enabled in AWS
Organizations (management account, `aws backup update-global-settings
--global-settings isCrossAccountBackupEnabled=true`), and both accounts in
the same organization. **Not verified:** the exact key-policy principals
AWS needs for a cross-account copy with customer managed keys. Test it in a
sandbox organization before relying on it. For the strongest isolation,
consider an AWS Backup logically air-gapped vault in the recovery account
(the plan schema exposes `target_logically_air_gapped_backup_vault_arn`). It's
not used here.

## Least privilege

| Principal | Permissions | Notes |
|---|---|---|
| Backup service role (primary) | AWS managed `AWSBackupServiceRolePolicyForBackup`, `...ForRestores`, `...ForS3Backup`, `...ForS3Restore` | Managed policies track new resource types. Use of the vault keys comes from key policies, not IAM |
| Restore-testing role (DR) | `...ForRestores`, `...ForS3Restore` | No backup permissions: it can't create recovery points or copies |
| Validator Lambda (DR) | `DescribeRestoreJob`, `PutRestoreValidationResult`; read-only `Describe*`/`ListTags*`/`Scan`/`GetObject`/`ListBucket`; `kms:Decrypt` on the DR key only via S3 and DynamoDB; its own log group | No delete permissions unless `early_cleanup = true`, and then only on resources with the restore-testing tag (`Null` condition on `aws:ResourceTag/<key>`) |
| Break-glass role | Not created here | The only principal the vault policies exempt. Assuming it should page someone |
| EventBridge, CloudWatch, AWS Backup → SNS | Topic policy per service, scoped by `aws:SourceAccount` (and by rule ARN for EventBridge). TLS required | |

Known broad scopes, kept on purpose:

- The validator reads `arn:aws:s3:::*` and `Describe*` on `*` because
  restored resource names are generated per test. Everything granted is
  read-only, and the function runs in the DR region on test resources.
  Tightening it would mean a restore-metadata naming convention plus
  `StringLike` resource ARNs. That's worth doing once the names are confirmed
  in a live run.
- `backup:PutRestoreValidationResult` on `*`: restore job ARNs aren't known
  in advance.

## The cleanup interlock

AWS Backup restore testing deletes restored resources itself after the
validation window. The validator never needs to delete anything. Early
cleanup is opt-in and has two independent locks:

1. **Code:** `cleanup()` reads the resource's tags and refuses unless the
   restore-testing tag (`awsbackup-restore-test` by default) is present. S3
   buckets are never deleted by the function at all.
2. **IAM:** the delete actions are only granted with
   `Null: aws:ResourceTag/<key> = false`.

A misrouted event, say a manual restore over a production name or a
forged event, therefore can't delete a real resource. **Unverified:** the
exact tag key AWS Backup applies to restore-testing resources. It's a
variable (`restore_test_tag_key`) for that reason. Confirm it on the first
live test before enabling early cleanup.

## Data handling

- Restored test databases contain production data. They come up in the
  subnet group named by `restore_metadata_overrides` (isolated, no route to
  production or the internet), and only the validator's security group
  should reach them.
- The validator logs counts, states and object keys, never row contents or
  object bodies.
- Job-history exports contain account IDs and ARNs. `jobs-*.json` is
  git-ignored. Only the synthetic sample is committed.
