# Security

Scope: the infrastructure in `terraform/`, the chart in `helm/dr-app`, and
the failover CLI. Everything is synthetic and unaudited. This page records
the controls that are in the code and the gaps that are not.

## Identity and access

| Principal | Mechanism | Scope |
|---|---|---|
| Cluster admins | EKS access entries + `AmazonEKSClusterAdminPolicy` | Only the role ARNs in `cluster_admin_principal_arns`; the cluster creator gets nothing implicitly (`bootstrap_cluster_creator_admin_permissions = false`) |
| Order API pods | EKS Pod Identity, `orders/order-api` | `GetSecretValue` on its secret name in its own region, `s3:Get/PutObject` on its own region's bucket, `kms:Decrypt/GenerateDataKey` on the regional key via Secrets Manager or S3 only |
| Load Balancer Controller | EKS Pod Identity, `kube-system/aws-load-balancer-controller` | The controller's policy (`policies/aws-load-balancer-controller.json.tftpl`), with create/modify/delete conditioned on the `elbv2.k8s.aws/cluster` tag |
| S3 replication | Role trusted by `s3.amazonaws.com` | Read source versions, write replicas, both regional keys limited by `kms:ViaService` and the bucket's encryption context |
| Failover operator | Your SSO role | Needs `rds:FailoverGlobalCluster`, `rds:RemoveFromGlobalCluster`, `rds:Describe*`, `cloudwatch:GetMetricStatistics`, `route53:ChangeResourceRecordSets` on one zone, and `helm upgrade` rights on one release per cluster |

Both Pod Identity roles restrict the trust to `aws:SourceAccount` and
`aws:SourceArn` (the cluster ARN). A role created for the DR cluster
cannot be assumed by a pod in the primary cluster, and the reverse holds
too.

The app role is region-scoped on purpose. A pod in us-west-2 never needs
anything in us-east-1. If it did, the DR region would quietly depend on
the region it is supposed to replace.

## Encryption

- **One customer managed key per region**, rotation on. It encrypts EKS
  Secrets (envelope encryption), Aurora storage and Performance Insights,
  the S3 bucket (bucket keys on), Valkey at rest, the Secrets Manager
  secret or replica, and the EKS control plane log group.
- **No multi-Region keys.** A key that is disabled, has its policy
  broken, or is scheduled for deletion in one region does not affect the
  other region's data. Replicated data is re-encrypted with the
  destination key (Aurora secondary, S3 replicas, secret replica).
- **In transit:** ALB listeners on TLS 1.3/1.2
  (`ELBSecurityPolicy-TLS13-1-2-2021-06`) with HTTP redirected to HTTPS.
  Valkey with `transit_encryption_mode = "required"`. S3 bucket policies
  deny non-TLS requests. Aurora connections should use `sslmode=verify-full`
  (an app-side setting).
- **The database password never reaches Terraform state.** It is generated
  by an ephemeral `aws_secretsmanager_random_password` and written through
  write-only arguments (`master_password_wo`, `secret_string_wo`). Rotation
  is a version bump.

## Network

- Data subnets have no route to the internet. Aurora and Valkey security
  groups accept 5432 and 6379 only from the EKS cluster security group.
- The EKS API endpoint is private by default. A public endpoint needs an
  explicit CIDR list, and `0.0.0.0/0` is rejected by validation.
- The default security group in each VPC is emptied (no rules).
- Kubernetes NetworkPolicy, enforced by the VPC CNI: default deny for the
  release's pods; ingress to the API only from the VPC CIDR on 8080 (ALB
  targets are pod IPs); egress to DNS, the data subnets, the Pod Identity
  agent and HTTPS.

## Workloads

Every container runs as non-root UID 10001, with a read-only root
filesystem, all capabilities dropped, no privilege escalation, and seccomp
`RuntimeDefault`. Every container has resource requests and a memory
limit, plus startup, readiness and liveness probes. A `/tmp` emptyDir is
capped at 64 Mi. The service account doesn't mount the Kubernetes API
token, because the pods never call the Kubernetes API. The chart's schema
rejects the `latest` image tag. `test_helm_static.py` asserts all of this
on the rendered output for both values files.

## Failover controls

- **Confirm token.** `execute` needs `--confirm <global-cluster-id>`. A
  mismatch is refused and logged before anything else happens.
- **Split-brain guards** ([ADR 0005](decisions/0005-fencing-before-promotion.md)):
  no promotion while another unfinished run has promoted the other region,
  and none while two unfenced writers exist. Failback needs
  `--rebuild-confirmed`, and the pre-check verifies it.
- **Audit log.** One JSON line per run start, step transition, refusal and
  completion, with actor, run ID, mode, regions and detail, fsynced before
  the tool moves on.
- **Fakes by default.** The CLI only touches AWS with `--adapters aws` and
  an explicit `--config`.

## Gaps (not implemented)

- **Hard fencing at the database.** Fencing scales workers to 0 and moves
  DNS. It does not revoke the old writer's database access. A stronger
  fence would revoke the application role's login on the old cluster, or
  deny `rds-db:connect` in that region with an SCP, as part of step 2.
- **State and audit storage.** Local files in this reference. Production
  needs a bucket outside both regions (or replicated), with versioning,
  object lock on the audit log, and a lock to stop two runs at once.
- **No WAF** on the ALBs. See the sibling
  [cloud-security-waf-automation](../../cloud-security-waf-automation/) project.
  `alb.ingress.kubernetes.io/wafv2-acl-arn` is the hook.
- **No VPC flow logs, GuardDuty EKS protection, or interface endpoints.**
  HTTPS egress for AWS APIs goes through NAT. With interface endpoints
  for Secrets Manager, STS and ECR, the NetworkPolicy's `0.0.0.0/0:443`
  rule could be narrowed to the VPC CIDR.
- **The Load Balancer Controller policy is condensed** from the upstream
  `iam_policy.json` and must be compared against the upstream file for the
  controller version actually installed.
- **Image signing and admission policy** (for example, verifying
  signatures with Kyverno) are out of scope. See the devsecops-pipeline
  project.
