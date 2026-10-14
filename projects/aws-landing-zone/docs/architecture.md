# Architecture

Reference implementation of a pattern used in production work; all names,
accounts and values are synthetic. Account names below are the keys in
`terraform/environments/management/terraform.tfvars.example`.

## OU and account tree

OUs are cut along policy boundaries ([ADR 0001](decisions/0001-ou-by-policy-boundary.md)).
Each box lists the SCPs attached **directly** to that node. Everything below
also inherits its ancestors' SCPs.

```mermaid
flowchart TB
  ROOT["Root<br/>FullAWSAccess · deny-leave-organization ·<br/>protect-security-services · region-allowlist<br/>(4/5, one slot kept free)"]
  MGMT["management account<br/>(SCPs never apply)"]
  SEC["Security OU<br/>+ deny-root-user · protect-s3-public-access-block"]
  INF["Infrastructure OU<br/>+ deny-root-user · protect-s3-pab · require-imdsv2"]
  WL["Workloads OU<br/>+ deny-root-user · protect-s3-pab · require-tags-on-create"]
  PROD["Prod OU<br/>+ require-imdsv2"]
  NP["NonProd OU<br/>+ require-imdsv2"]
  SB["Sandbox OU<br/>+ deny-root-user · protect-s3-pab · require-imdsv2"]
  SUS["Suspended OU<br/>+ deny-all"]

  ROOT --- MGMT
  ROOT --> SEC & INF & WL & SB & SUS
  WL --> PROD & NP
  SEC --> LA["log-archive"] & ST["security-tooling"]
  INF --> SS["shared-services"]
  PROD --> WP["workload-prod"]
  NP --> WN["workload-nonprod"]
  SB --> SBA["sandbox-alpha"]
```

Every node also has the AWS-managed `FullAWSAccess` attached. SCPs filter
permissions and never grant them, and an action must be allowed at **every**
level of the path. If you remove FullAWSAccess from an OU without replacing
it with an allow list, everything below that OU is implicitly denied.
`simulate_scp.py` models this, and reports "implicit: no SCP attached to X
allows the action".

The attachment layout is the file `policy/attachments.json`. Terraform
(`environments/management`), `check_scps.py` and `simulate_scp.py` all read
it.

| Target | Direct SCPs | Why here |
|---|---|---|
| root | FullAWSAccess, deny-leave-organization, protect-security-services, region-allowlist | Universal. One slot stays free for an emergency deny |
| security | + deny-root-user, protect-s3-public-access-block | Log archive and security tooling: no root, no PAB changes |
| infrastructure | + deny-root-user, protect-s3-pab, require-imdsv2 | Shared services run EC2 (directory, CI runners) |
| workloads | + deny-root-user, protect-s3-pab, require-tags-on-create | Shared by Prod and NonProd |
| prod / nonprod | + require-imdsv2 | Leaves room for environment-specific SCPs (4 slots free) |
| sandbox | + deny-root-user, protect-s3-pab, require-imdsv2 | No tag requirement, to keep experiments cheap to start |
| suspended | + deny-all | Quarantine. One move, no policy edit |

## Log flow

```mermaid
flowchart LR
  subgraph MA["management account"]
    TRAIL["Org CloudTrail<br/>multi-region, global events,<br/>log file validation"]
  end
  subgraph MEM["member accounts"]
    API["API calls"] -.->|"recorded by org trail"| TRAIL
    CFG["Config recorders<br/>(delivery channel)"]
  end
  subgraph LA["log-archive account"]
    KMS["KMS key<br/>rotation on"]
    B[("S3 bucket<br/>Object Lock GOVERNANCE,<br/>versioning, TLS-only")]
    G["Glacier after 90 d,<br/>expire after 7 y"]
    AGG["Config org aggregator<br/>(delegated admin)"]
  end
  TRAIL -->|"PutObject AWSLogs/&lt;org-id&gt;/*<br/>aws:SourceArn = trail"| B
  CFG -->|"PutObject AWSLogs/*/Config/*<br/>aws:SourceOrgID = org"| B
  TRAIL -. "GenerateDataKey<br/>(encryption context = trail)" .-> KMS
  B --> G
  MEM -. "Config data via<br/>AWSConfigRoleForOrganizations" .-> AGG
```

- The trail lives in the management account (org trails must). Its bucket
  and key live in the log-archive account, so nobody who operates a workload,
  or the management account day to day, can delete logs.
- **Bucket policy**: TLS-only; CloudTrail writes pinned to this trail's ARN
  under both the management account's prefix and the organization prefix;
  Config writes pinned to the organization with `aws:SourceOrgID`, because
  every member account's delivery channel has a different source ARN; Object
  Lock bypass, lock reconfiguration and bucket deletion denied to everyone
  except the log-archive break-glass role.
- **Object Lock** is enabled at creation (it can't be added later) with a
  365-day governance default. [Security](security.md#log-integrity) covers
  governance versus compliance mode.
- **Provider aliases**: `aws.management` creates the trail, and
  `aws.log_archive` creates the rest. Both use `assume_role`.

## Network hub and route-table isolation

```mermaid
flowchart TB
  subgraph SS["shared-services account"]
    TGW{{"Transit Gateway<br/>no default route table<br/>shared to the org via RAM"}}
    RTP["rt-prod<br/>prod /16s + shared /16s<br/>0/0 → egress<br/>RFC 1918 → blackhole"]
    RTN["rt-nonprod<br/>nonprod /16s + shared /16s<br/>0/0 → egress<br/>RFC 1918 → blackhole"]
    RTS["rt-shared<br/>all /16s<br/>0/0 → egress<br/>RFC 1918 → blackhole"]
    subgraph EG["egress VPC 10.0.0.0/16"]
      TGWSUB["TGW subnets /28"] --> NAT["NAT GW per AZ"] --> IGW["IGW"]
    end
  end
  P1["prod-payments 10.16/16"] -- assoc --> RTP
  P2["prod-data 10.17/16"] -- assoc --> RTP
  N1["nonprod-payments 10.32/16"] -- assoc --> RTN
  N2["nonprod-data 10.33/16"] -- assoc --> RTN
  S1["shared-services 10.1/16"] -- assoc --> RTS
  EG -- assoc --> RTS
  RTP & RTN & RTS --- TGW
```

The model, as written in `modules/network-hub/main.tf`:

| Attachment environment | Associated with | Propagates into |
|---|---|---|
| prod | rt-prod | rt-prod, rt-shared |
| nonprod | rt-nonprod | rt-nonprod, rt-shared |
| shared | rt-shared | rt-prod, rt-nonprod, rt-shared |
| egress VPC | rt-shared | (none, static 0/0 routes point at it) |

- **Association** picks the table used to route traffic *from* an
  attachment. **Propagation** puts an attachment's CIDR *into* a table. Prod
  never propagates into rt-nonprod and nonprod never into rt-prod, so
  neither table has a route to the other.
- **The hairpin, and why the blackholes exist.** Every table has
  `0.0.0.0/0 → egress`. Without blackholes, a packet from prod to
  `10.32.0.5` (nonprod) matches `0.0.0.0/0` and goes to the egress VPC. The
  egress public subnets route `10.0.0.0/8` back to the TGW, and the egress
  attachment uses rt-shared, which knows nonprod. Isolation is gone.
  Blackholing `10.0.0.0/8`, `172.16.0.0/12` and `192.168.0.0/16` in every
  table fixes it: propagated /16s are more specific and still win, and
  every other private destination is dropped at the TGW.
- **No default route table** (`default_route_table_association` and
  `_propagation` disabled). Auto-accept is on so org accounts can attach
  without a manual step, but a new attachment routes nowhere until the hub
  associates it. That's the control point.
- **Egress VPC**: public subnets with a NAT gateway per AZ (or one, with
  `single_nat_gateway`), small TGW subnets routing `0.0.0.0/0` to the NAT
  in the same AZ, and appliance mode on the attachment so both directions of
  a flow stay in one AZ ([ADR 0003](decisions/0003-centralized-egress.md)).
- **Spokes** (`modules/spoke-vpc`) have private subnets only, no IGW, and
  `0.0.0.0/0 → TGW`. The CIDR is looked up in the plan by name, never typed.
  The module receives the whole plan and refuses an overlapping one. Flow
  logs record rejected traffic.

### Address plan

`policy/cidr-plan.json`: `/16` spokes from `10.0.0.0/8`, with the egress
VPC and a future on-premises block reserved. Overlaps are caught three ways:

1. `policy/cidr_plan.py` in CI (general overlap check with `ipaddress`).
2. A `check` block and a precondition on the Transit Gateway in
   `network-hub`. Both truncate each pair to the shorter prefix with
   `cidrsubnet(..., 0, 0)` and compare.
3. Variable validations in `spoke-vpc`, which reject non-canonical,
   non-/16, non-RFC 1918 or duplicate entries.

## Access model

```mermaid
flowchart LR
  IDP["Identity provider<br/>(SCIM groups)"] --> IC["IAM Identity Center<br/>(management account)"]
  IC --> PS1["AdministratorAccess<br/>1 h session"]
  IC --> PS2["PowerUserAccess<br/>+ inline deny IAM writes,<br/>Organizations, account, SSO<br/>4 h"]
  IC --> PS3["ReadOnlyAccess<br/>8 h"]
  IC --> PS4["BillingAccess<br/>4 h"]
  PS1 -->|"platform-admins"| A1["shared-services, workload-prod,<br/>workload-nonprod"]
  PS2 -->|"developers"| A2["workload-nonprod, sandbox-alpha"]
  PS3 -->|"developers, auditors"| A3["workload-prod, log-archive,<br/>security-tooling"]
  PS4 -->|"finance"| A4["management"]
  BG["Break-glass role<br/>LandingZoneBreakGlass"] -.->|"exempt from region deny,<br/>security-service and PAB protections"| A1
```

- **Groups only.** Assignments are `group → account → permission sets`. No
  users are created, and joiners and leavers are handled in the IdP.
- **Admin is short-lived**: a 1-hour session, assigned only where the
  platform team operates.
- **PowerUser can't touch identity**: the AWS-managed PowerUserAccess plus
  an explicit inline deny on IAM writes (service-linked roles excepted),
  Organizations, account, SSO and identity store actions. `iam:PassRole`
  stays, so existing roles can be used to deploy.
- **SCPs still apply on top.** An AdministratorAccess session in
  workload-prod still can't stop CloudTrail or work outside the allowed
  regions.
- **Break-glass** is an IAM role (`LandingZoneBreakGlass`), not an Identity
  Center permission set, so it keeps working if Identity Center or the IdP
  is down. See [operations](operations.md#break-glass-access).
