# Security

Reference implementation of a pattern used in production work; all names,
accounts and values are synthetic. This document covers the threat model
the landing zone is built around, what each control does, and what it
doesn't do.

## Threat model

| Threat | Control | Residual risk |
|---|---|---|
| A workload admin disables logging to cover tracks | `protect-security-services` SCP (CloudTrail, GuardDuty, Config, Security Hub); the org trail lives in management and its bucket in log-archive | Break-glass can still do it. Break-glass use must page |
| Logs deleted or altered after the fact | Object Lock (governance), versioning, log file validation (digests), bucket policy denying governance bypass except break-glass | Governance mode can be bypassed by break-glass, and compliance mode would remove even that. See below |
| Stolen root credentials of a member account | `deny-root-user` on every OU below root; root MFA at vending; consider centralized root access (no member root passwords at all) | SCPs don't cover the few root-only tasks, and don't apply to the management account |
| An account leaves the org and escapes all controls | `deny-leave-organization` on the root | The management account can still remove an account |
| Resources launched in unmonitored regions | `region-allowlist` with `aws:RequestedRegion` | Global services are exempt by design and are covered by the multi-region trail |
| SSRF steals instance credentials through IMDSv1 | `require-imdsv2` denies launches without `HttpTokens=required` and locks metadata option changes to break-glass | Instances launched before the SCP need a migration |
| Public S3 exposure | Account-level public access block in every account (baseline), with changes denied by SCP; bucket-level PAB stays editable for normal workflows | Not a substitute for bucket policies. Access Analyzer reports external access |
| Prod reachable from nonprod (lateral movement) | Separate TGW route tables, an explicit propagation matrix, RFC 1918 blackholes against the egress hairpin, no default TGW route table | The shared-services VPC reaches both. Its security groups and NACLs are the boundary |
| Excessive human privilege | Identity Center groups only; Admin 1 h; PowerUser denies IAM writes and Organizations; ReadOnly for prod by default | Admin sessions are still admin within the SCPs |
| Untracked spend or untagged resources | Tag policy (allowed values), `require-tags-on-create` SCP (presence), budgets with actual and forecast alerts | Only EC2 instances and volumes and RDS instances require tags at creation |

## SCP design rules

- **Deny lists, not allow lists.** Every shipped SCP is `Deny`, on top of
  FullAWSAccess. Allow-list SCPs (removing FullAWSAccess) are more secure
  on paper, but every new service then needs an SCP change. That's worth it
  only for very constrained OUs. `check_scps.py` rejects `Allow` with
  wildcards, so an accidental broad allow can't slip in.
- **Exemptions by `aws:PrincipalArn`.** Break-glass and security automation
  roles are exempted with `ArnNotLike` on a role-name pattern that's the
  same in every account. Never exempt by tag on the principal, because tags
  can be edited by the people you're restricting.
- **The region deny uses `NotAction`.** That way it denies everything except
  global services. `Action: "*"` with a region condition would break IAM,
  STS (the global endpoint is us-east-1), Organizations, CloudFront,
  Route 53, Support and Budgets in every non-us-east-1 home region.
  `check_scps.py` requires the global exemptions.
- **What SCPs never do.** They don't grant anything. They don't affect the
  management account or service-linked roles. They do affect the root user
  of member accounts, which is how `deny-root-user` works.
- **Size and count.** At most 5,120 characters (the module minifies before
  upload) and 5 directly attached per target, FullAWSAccess included. Both
  are checked in CI and in Terraform.

## Log integrity

- **Separation.** The trail can only be changed from the management account,
  and the logs can only be deleted from the log-archive account. Nobody
  operating a workload has either.
- **Object Lock, governance mode, 365 days by default.** Governance mode
  protects against everyone without `s3:BypassGovernanceRetention`, and the
  bucket policy denies that permission to everyone except the log-archive
  break-glass role. **Compliance mode** (`object_lock_mode = "COMPLIANCE"`)
  can't be shortened or removed by anyone, including the root user, until
  retention ends. It's the stronger control, and the right one when a
  regulator requires it. The risk is that a misconfigured retention period
  keeps paying for storage for years. Start with governance, prove the
  lifecycle, then decide.
- **Log file validation.** CloudTrail delivers hourly digest files, so
  `aws cloudtrail validate-logs` proves which log files were delivered and
  unchanged.
- **Encryption.** A customer managed key with rotation. CloudTrail may use
  it only for this trail (`aws:SourceArn` plus the CloudTrail encryption
  context). Decryption is limited to principals in the log-archive account,
  and Config may encrypt only from within the organization
  (`aws:SourceOrgID`).
- **Scoped writes.** CloudTrail writes are pinned to the trail's ARN. Config
  writes are pinned to the organization with `aws:SourceOrgID`, because a
  per-account `aws:SourceArn` list would need editing for every new account.
  TLS is enforced for every request.

## Identity

- **People come through Identity Center, roles through federation.** The
  baseline still sets a strict IAM password policy (16+ characters, 24
  previous passwords remembered), because IAM users may exist for
  break-glass.
- **Short admin sessions.** AdministratorAccess is 1 hour, so a hijacked
  browser session expires quickly.
- **PowerUser is "build, don't govern".** The inline deny makes the
  boundary explicit: no IAM writes except service-linked roles, and no
  Organizations, account, SSO or identity store actions.

## Network

- **No internet ingress in spokes.** No IGW, and the only route out is
  through the TGW to the central NAT gateways. Inbound internet services go
  through a separate ingress pattern (an ALB in the workload account with
  WAF, see the sibling project), not through the hub.
- **Central egress gives one place to inspect and allow-list** (stable NAT
  IPs for partners). It's also one place to fail, so there's a NAT gateway
  per AZ by default ([ADR 0003](decisions/0003-centralized-egress.md)).
- **Flow logs** record rejected traffic in every spoke.

## Checked in CI

- `check_scps.py`: JSON, size, version, Sids, no wildcard allows, region
  deny exemptions, attachment count and references.
- `simulate_scp.py`, in the tests: the concrete behaviours above (region,
  root, IMDS, tags, leave org, Suspended, break-glass) as regression tests.
- `cidr_plan.py`: RFC 1918, prefix, no overlaps.
- Terraform `fmt` and `validate` in every module and environment, plus
  text-level invariants (no credentials in providers, placeholder account
  IDs only, the isolation matrix, `prevent_destroy` on accounts).

## Not covered

GuardDuty, Security Hub, Config recorders and conformance packs in member
accounts; Macie; centralized root access management; permission
boundaries for developer-created roles; EventBridge alerting on
break-glass use; VPC endpoints for private access to AWS APIs (they would
also cut NAT data processing costs); DNS firewall and network firewall on
the egress path.
