# Security

> Design intent, validated with `terraform validate`, `ansible-lint` and
> `python3 -m unittest` only. Never applied, never run against a real
> account, VMware environment or host. Evidence is the type of record this
> project expects to produce in operation (see docs/operations.md's restore
> test table), not a claim about a real deployment.

## Threat model: a compromised edge-zone workload, or the link itself

Two threats this design specifically answers:

1. **A compromised customer-facing workload in the edge zone tries to
   reach the regulated zone or on-prem directly.** The segmentation
   module's edge-zone security group has no egress rule naming the
   regulated zone's CIDR on anything but 8443, and no NACL rule past that
   either. The regulated zone's own security group only accepts 8443 from
   the edge zone's security group id -- a compromised edge pod can open a
   socket to port 8443 and nothing else on the regulated subnet.
2. **The hybrid link is down, flapping, or an attacker is attempting to
   degrade it (a denial-of-service against availability, not
   confidentiality).** The graceful-degradation pattern (`src/degrade/`)
   means an impaired link produces queued work, not failed customer
   requests or a fallback to an insecure direct path -- there is no
   "temporarily bypass the VPN" escape hatch in this design to make
   outages shorter; see docs/architecture.md's sequence diagram.

| Attacker/failure step | Control in this design | Residual risk |
|---|---|---|
| Edge workload tries to reach on-prem CIDR directly | No route; only the regulated route table gets VPN gateway route propagation (`route_table_ids = [regulated route table]` in the reference root) | A future Terraform change that adds propagation to the edge route table would need to pass `tests/test_terraform_static.py::ReferenceRootTests::test_only_the_regulated_route_table_gets_on_prem_propagation` first |
| Edge workload tries to reach the regulated zone on a port other than 8443 | Security group default-deny (no matching rule); NACL rule 100 only allows 8443, rule 32766 denies everything else | A misconfigured security-group rule on one *instance* in the regulated subnet is still caught by the subnet-wide NACL (defense in depth) |
| Someone adds `0.0.0.0/0` to the regulated zone's allowed_ingress/egress by mistake | `lifecycle.precondition` on `aws_security_group.this` fails `terraform plan` with an explicit error message naming the rule | Precondition only runs on `plan`/`apply`; a reviewer still needs to actually run `terraform plan` before merging, this isn't a substitute for that |
| On-prem device compromise used to pivot into AWS | Segmentation is symmetric: the regulated zone's egress is scoped to the on-prem CIDR on 5432 only, nothing wider; the connectivity module's route propagation only reaches the regulated route table, not the edge one | A compromised on-prem host that can reach 5432 on the regulated zone is still bounded by the regulated zone's own security group for anything it tries from there |
| Link down, attacker (or an outage) tries to make it look like a service failure | `DegradingClient` returns `202 Accepted` + queues rather than `5xx`; `on_degrade` hook feeds an alert/metric so a flapping link is observable, not silently absorbed | A sustained outage that exhausts `max_attempts` on replay surfaces as `permanently_failed` entries requiring manual reconciliation -- documented in docs/operations.md's incident response section |

## PCI-DSS scope reduction (the segmentation argument)

The regulated zone is modeled on a cardholder-data-environment (CDE)
segmentation boundary: PCI-DSS requires that systems outside the CDE be
"adequately segmented" to be excluded from scope, which in practice means
exactly what this project's security groups and NACLs do --
default-deny, explicit allow-list, no path from the broader network to the
CDE-equivalent zone except the named flows. The edge zone (public-facing,
handles no cardholder data directly, only talks to the regulated zone over
one named internal API port) is the piece of this design PCI-DSS scope
reduction is actually for: keeping it segmented is what lets an assessor
treat it as out of scope, rather than pulling the entire customer-facing
fleet into the CDE.

This repository does not claim PCI-DSS compliance or certification --
that requires an actual assessment of an actual running system by a
Qualified Security Assessor. What it demonstrates is the segmentation
*mechanism* an assessor would look for.

## Least-privilege IAM and secrets management

Not built in this project (the IAM/secrets layer for the EKS/RDS workload
lives in `../aws-landing-zone` and `../eks-secrets-store-csi`), but the
boundary this project owns has its own narrow IAM surface:

- The VPN connection's pre-shared keys/certificates are the actual secret
  this boundary depends on. They belong in AWS Secrets Manager or SSM
  Parameter Store (SecureString) with rotation on the schedule the on-prem
  network team can actually execute (PSK rotation requires coordinated
  on-prem device reconfiguration, so this is a change-managed rotation, not
  an automatic one) -- never in Terraform state as a plain variable, and
  never in this repository (no real PSK exists here to leak).
- Terraform's own execution role for `terraform/modules/connectivity` and
  `terraform/modules/segmentation` needs exactly `ec2:*VpnGateway*`,
  `ec2:*CustomerGateway*`, `ec2:*VpnConnection*`, `ec2:*SecurityGroup*`,
  `ec2:*NetworkAcl*` and `ec2:*Route*` -- not the account-wide admin a
  portfolio reference's placeholder provider block implies. A real
  deployment scopes this role per `../aws-landing-zone`'s pipeline-identity
  pattern.

## Vulnerability remediation through SOC operations

The log-shipping piece of the Ansible baseline role
(`ansible/roles/baseline/templates/log-shipper.conf.j2`) is the mechanism:
every host in both estates ships to the same SIEM/SOC collector endpoint
(`baseline_log_shipping_endpoint` in `group_vars/all.yml`), so a
vulnerability finding on an on-prem host and one on an AWS host flow into
the same triage queue rather than two separate, estate-specific tools. The
patch-cadence tasks (`unattended-upgrades` on Debian/Ubuntu,
`dnf-automatic` on Amazon Linux) are the remediation half: both run on the
same weekly cadence (`baseline_patch_cron_schedule`, shared in
`group_vars/all.yml`, not duplicated per estate) so a CVE advisory has the
same time-to-patch SLA regardless of which side of the hybrid link the
vulnerable host is on.

## Secrets and values in this repository

Every CIDR, IP, host and ARN-shaped string in this project's Terraform,
Ansible and tests is a documentation-safe placeholder: RFC 5737 TEST-NET
ranges (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`) for anything
representing a public/on-prem address, RFC 1918 ranges for private AWS
CIDRs, and `*.internal.example` / `*.example.com`-shaped names for hosts.
`terraform/modules/connectivity`'s `on_prem_gateways` variable enforces the
TEST-NET restriction with a `validation` block, not just a convention.
