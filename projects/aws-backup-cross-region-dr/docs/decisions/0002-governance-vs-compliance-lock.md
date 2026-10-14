# ADR 0002: Vault Lock in governance mode by default, compliance mode opt-in

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-backup-cross-region-dr (portfolio implementation)

## Context

AWS Backup Vault Lock has two modes:

- **Governance mode** (`changeable_for_days` unset): the lock enforces
  minimum and maximum retention, and a principal with
  `backup:DeleteBackupVaultLockConfiguration` can remove it.
- **Compliance mode** (`changeable_for_days` set, minimum 3): during the
  grace period the lock can still be removed. **After the grace period it
  is immutable.** Nobody can remove it, shorten retention below the
  minimum, or delete the vault while it holds recovery points. That
  includes administrators, the account root user and AWS Support. The only
  way out is to wait until every recovery point has expired.

Compliance mode is the strongest protection against ransomware and insiders.
It's also a one-way door: a mistaken `max_retention_days`, a wrong vault or
a retention that turns out to breach a data-deletion obligation can't be
undone.

## Decision

1. **Governance mode is the default** (`vault_lock_mode = "governance"`, and
   `"mode": "governance"` in `policy/backup-policy.json`).
2. **Compliance mode is one value away** (`"mode": "compliance"`), with the
   grace period from `changeable_for_days` (validated ≥ 3 in Terraform and by
   BKP-005 in the policy checker).
3. Governance mode is paired with an **SCP** denying
   `DeleteBackupVaultLockConfiguration`, vault-policy changes and recovery
   point deletion to everyone but the break-glass and deployer roles (see
   [security](../security.md#immutability)). That makes governance mode
   resistant to a compromised workload admin without being irreversible.
4. **Switching to compliance mode requires:**
   - a written retention decision from the data owner and legal or
     compliance (the min and max will bind for years);
   - a sandbox rehearsal with the exact values;
   - applying with a grace period long enough to review (`changeable_for_days`
     of 7 or more, not the minimum 3), and an alert reminding the team
     before it ends;
   - the policy-file PR approved by two people, with a comment linking this ADR.

## Consequences

Good:

- **Safe to adopt.** Teams can turn on locking on day one without risking a
  permanent mistake.
- **Upgrade path.** Moving to compliance is a reviewed, one-line change once
  the retention values have been lived with.
- **The variable documentation, this ADR and the operations runbook all say
  "irreversible" in plain words**, so nobody flips it casually.

Accepted costs:

- **Governance mode is only as strong as the SCP and IAM around it.** A
  principal who can both remove the lock and edit the vault policy can
  delete recovery points. The cross-account DR vault reduces this risk
  further.
- **Two places to keep consistent:** the lock range and every rule's
  retention. A retention outside the range makes jobs *fail*, so BKP-006 and
  a Terraform validation both check it.

## Alternatives considered

- **Compliance mode by default.** Strongest, and wrong for a module that
  gets copied into new accounts: the first typo becomes permanent.
- **No lock, only the vault access policy.** An admin can rewrite the policy
  in one API call. That's not immutability.
- **S3 Object Lock-style immutability per service.** That only exists for
  S3. Vault Lock covers every type in the vault.
