# Security

Working portfolio implementation; never deployed. Controls below are what
the Terraform and code define; none has been tested against a real account.

## Network

| Path | Allowed from | Where |
|---|---|---|
| ALB 443 / 80 (redirect) | `production_ingress_cidrs` (default `0.0.0.0/0`) | `alb.tf`, one ALB per environment |
| ALB test listener 8443 | that environment's `test_listener_cidrs` only | `alb.tf` |
| ALB to tasks | ALB egress only to the VPC CIDR, container port only | `alb.tf` |
| Tasks, container port | the ALB security group only (SG reference) | `security.tf` |
| Tasks, egress | TCP 443 (ECR, Secrets Manager, Logs via NAT or endpoints) | `security.tf` |
| Hook Lambdas, egress | TCP 443 and the test port | `security.tf` |

- **The test listener is the sensitive one.** It serves a version nobody has
  approved yet. Terraform validation rejects an empty list or any `/0`, and
  `check_bluegreen_policy.py` (BG005) rejects `0.0.0.0/0`, `::/0` and invalid
  CIDRs before Terraform runs. Include only the team's VPN/office range and
  the NAT EIPs the hooks egress through.
- Tasks run in private subnets with no public IP.
- Each ALB drops invalid header fields, uses defensive desync mitigation
  and the `ELBSecurityPolicy-TLS13-1-2-2021-06` policy (TLS 1.2 minimum).
- Each environment has its own ALB and ALB security group, so test CIDRs
  for one environment never open another's listeners
  ([ADR 0004](decisions/0004-alb-per-environment.md)).

## IAM

| Role | Can do | Can't do |
|---|---|---|
| Task execution (per env) | pull from the one ECR repository; read the one app secret; write to the one log group; `ecr:GetAuthorizationToken` (no resource scoping exists) | read other secrets, pull other repositories |
| Task (per env) | nothing: the app calls no AWS APIs | anything |
| CodeDeploy service role (per env) | AWS managed `AWSCodeDeployRoleForECS` | see below |
| Hook Lambdas (per env) | `PutLifecycleEventHookExecutionStatus` and `GetDeployment` on its own deployment group; `ecs:DescribeTaskDefinition` (no resource scoping exists); write its log groups; manage its ENIs | report on another environment's deployments |

All service trust policies except Lambda's carry an `aws:SourceAccount`
condition (confused-deputy protection).

**The CodeDeploy role is the accepted gap.** `AWSCodeDeployRoleForECS`
lets the role manage task sets on any ECS service, modify any listener or
rule, invoke any `CodeDeployHook_*` function, read alarms, and pass roles to
ECS tasks. That's broader than one service. A hand-scoped policy is
possible (task sets on one service ARN, `ModifyListener` on the
environment's production and test listeners, `lambda:InvokeFunction` on the two
hook ARNs, `iam:PassRole` on the two task roles with
`iam:PassedToService = ecs-tasks.amazonaws.com`), but whether CodeDeploy's
internal calls fit it can only be proven with a real deployment, so the
project doesn't claim it. The hook names start with `CodeDeployHook_` so the
managed policy can invoke them without extra grants.

**Who may deploy.** Not in this Terraform, but required: separate
permissions for `codedeploy:CreateDeployment` (CI's role) and
`codedeploy:ContinueDeployment` on the prod group (release approvers), so
the person shipping can't also approve the production reroute.
`ecs:RegisterTaskDefinition` needs `iam:PassRole` on exactly the execution
and task roles.

## Secrets

- One Secrets Manager secret per environment, created **without a version**:
  the value is set with `put-secret-value`, so it never enters Terraform
  state.
- The task definition references `<arn>:password::`, injecting one JSON key,
  not the whole document.
- The app never logs or returns the value (`/version` reports only
  `db_password_loaded`), and the config's `repr` omits it. Tests check both.

## Supply chain

- ECR tags are **immutable**; `render_appspec.py` refuses `latest` and
  untagged images, and `bootstrap_image` validation refuses them in
  Terraform. A task definition revision therefore always means one image.
- The hooks verify the running version: `/version` must return the image
  tag of the task definition being deployed, read from the deployment
  itself.
- ECR scan on push is enabled. There is no image signing or admission
  check; see the delivery sibling for a scan gate before push.

## Container

- Multi-stage Dockerfile; the runtime stage copies only the checked sources.
- Runs as UID 10001; the task definition repeats `user` and sets
  `readonlyRootFilesystem`; `initProcessEnabled` reaps zombies and forwards
  signals.
- The base image is pinned by tag (`python:3.12.12-slim-bookworm`,
  multi-arch). Pin by digest in a real pipeline.

## Logging and audit

- Service and hook logs go to CloudWatch Logs with per-environment
  retention (7/14/90 days). They use the default CloudWatch Logs
  encryption; add a KMS key if policy requires one.
- Every hook run logs one JSON line with the deployment ID, status, checks
  and p95. CodeDeploy deployments, reroutes and stops are in CloudTrail.
- The access log never records query strings.
