# DevOps & Cloud Architecture Portfolio

Working, tested infrastructure code behind the projects on
[salahuddin.wesaveall.com/projects](https://salahuddin.wesaveall.com/projects) — by **Muhammad Salahuddin**, Senior DevOps Engineer.

20 self-contained projects spanning AWS, GCP, Azure, Kubernetes, GitOps, security, FinOps, DR and AIOps. Every project runs and validates **locally, with no cloud account** — Terraform is validated only, never applied, and every example uses synthetic data (`example.com`, placeholder account IDs, illustrative prices).

**1,540 unit tests · all passing · stdlib Python, zero dependencies.**

## How each project is labeled

| Label | Meaning |
|---|---|
| **Production case study** | A sanitized write-up of real work from my CV. The code here is a synthetic reference implementation of that pattern — no client names, domains, account IDs or real figures. |
| **Portfolio implementation** | Built for this portfolio from scratch, on synthetic data, to demonstrate a specific skill end-to-end. |
| **Reference architecture** | A fully implemented and tested design that draws on real experience but isn't presented as a production deployment. |

## Projects

| # | Project | Label | Tests | What's in it |
|---|---|---|---|---|
| 01 | [Multi-region EKS disaster recovery](projects/aws-multi-region-eks-dr/) | Production case study | 100 | Two-region Terraform, Aurora Global Database, hardened Helm chart, failover orchestrator with split-brain guards, runbooks |
| 02 | [n8n on EKS with KEDA scale-to-zero](projects/n8n-keda-automation-platform/) | Production case study | 96 | Queue-mode n8n, KEDA Redis-list scaling, CSI-mounted secrets, verified against the real image |
| 03 | [AWS Graviton ARM64 migration](projects/graviton-arm64-migration/) | Reference architecture | 45 | Multi-arch image build, scheduling-based rollout/rollback across EKS node groups, no separate ECS track |
| 04 | [Enterprise AWS landing zone](projects/aws-landing-zone/) | Production case study | 130 | Organizations, SCPs, log archive account, IAM Identity Center, Transit Gateway hub, SCP checker and simulator |
| 05 | [GitOps delivery platform](projects/gitops-delivery-platform/) | Production case study | 85 | Argo CD ApplicationSet, PR-based promotion across dev/staging/prod, drift report, Rollouts canary with analysis |
| 06 | [DevSecOps supply-chain pipeline](projects/devsecops-pipeline/) | Production case study | 52 | Reusable GitHub Actions workflow — gitleaks, Semgrep, Trivy, SBOM, cosign, ZAP — plus a workflow-hardening linter |
| 07 | [GCP AI pharmacy platform](projects/gcp-ai-pharmacy-platform/) | Production case study | 41 | Private regional GKE with Workload Identity, tainted/scale-to-zero AI node pool, private HA Cloud SQL, per-secret IAM |
| 08 | [Azure AKS enterprise platform](projects/azure-aks-platform/) | Reference architecture | 46 | Hub-and-spoke networking with forced tunneling, private AKS, Azure RBAC, federated workload identity (no client secrets) |
| 09 | [Multi-cloud Kubernetes platform](projects/multi-cloud-kubernetes/) | Reference architecture | 51 | One Helm chart deployed to EKS/AKS/GKE via three overlays, tested to diverge only on identity/ingress/storage, one ArgoCD ApplicationSet |
| 10 | [Serverless event-driven pipeline](projects/aws-serverless-event-driven/) | Portfolio implementation | 74 | API Gateway, Lambda, SQS, DynamoDB idempotency, EventBridge |
| 11 | [SLO-driven observability](projects/observability-sre-platform/) | Production case study | 79 | SLOs as code → burn-rate alerts, dashboards, runbooks, error-budget policy; `promtool`-tested |
| 12 | [Hybrid cloud fintech architecture](projects/hybrid-cloud-fintech/) | Production case study | 40 | Redundant Site-to-Site VPN, a segmentation module that fails validation if the regulated zone is ever exposed, outage-queue/replay client, shared Ansible baseline |
| 13 | [Cloud security & WAF automation](projects/cloud-security-waf-automation/) | Portfolio implementation | 99 | WAF count-then-block rollout, GuardDuty/Security Hub routing, policy-as-code with SARIF output |
| 14 | [FinOps cost-optimization toolkit](projects/finops-cost-optimization/) | Portfolio implementation | 71 | Cost allocation, rightsizing, commitment planning, budget gate, Terraform cost guardrails |
| 15 | [AI-powered cloud operations](projects/ai-cloud-operations/) | Portfolio implementation | 66 | Rolling-baseline anomaly detection, deploy/alert correlation, allow-listed auto-remediation with an append-only audit log, no-op-by-default LLM interface |
| 16 | [CodePipeline container delivery](projects/aws-codepipeline-container-delivery/) | Portfolio implementation | 39 | CodeBuild with a Trivy gate, immutable image tags, ECS deploy with manual approval |
| 17 | [AWS Backup cross-region DR](projects/aws-backup-cross-region-dr/) | Portfolio implementation | 118 | Vault lock, cross-region copies, restore-testing validator, RPO/RTO reporting |
| 18 | [CloudFront + S3 static delivery](projects/cloudfront-s3-static-delivery/) | Portfolio implementation | 129 | Origin Access Control, security headers, a tested Lambda@Edge/CloudFront Function, OIDC deploys |
| 19 | [ECS Fargate blue/green](projects/ecs-fargate-blue-green/) | Portfolio implementation | 105 | CodeDeploy canary/linear shifts with test-listener hooks and alarm-triggered rollback |
| 20 | [EKS secrets with the CSI driver](projects/eks-secrets-store-csi/) | Portfolio implementation | 74 | Secrets Manager mounted via Pod Identity and the Secrets Store CSI driver, live rotation drill, secret scanners |

Every Terraform directory validates against `hashicorp/aws` 6.68.0 (plus `google` and `azurerm`/`azuread` for the GCP and Azure projects). Every Helm chart passes `kubeconform -strict`, CRDs included. Every CI workflow passes the repo's own workflow-hardening linter: actions pinned to commit SHAs, least-privilege tokens, no persisted credentials.

## Project details

**01 · [Multi-region EKS disaster recovery](projects/aws-multi-region-eks-dr/)**
A synthetic order API on EKS, deployed warm-standby across two regions with Aurora PostgreSQL Global Database, S3 replication and Route 53 failover. A failover orchestrator moves the writer between regions in a fixed, fenced order and refuses anything that could leave two writers.

**02 · [n8n on EKS with KEDA scale-to-zero](projects/n8n-keda-automation-platform/)**
Self-hosted n8n in queue mode on EKS: HPA-scaled webhook processes enqueue work in ElastiCache Valkey, and KEDA scales workers on queue depth down to zero when idle. Secrets (DB, Redis, encryption key) come from Secrets Manager via the CSI driver, never baked into the image.

**03 · [AWS Graviton ARM64 migration](projects/graviton-arm64-migration/)**
A staged x86→Graviton migration where every image is built once as a multi-arch manifest under one ECR tag. Moving a service between architectures becomes a Kubernetes scheduling decision (`nodeSelector`/`affinity`), so rollback is one `helm upgrade` away, not a rebuild.

**04 · [Enterprise AWS landing zone](projects/aws-landing-zone/)**
A multi-account AWS foundation: an Organization with policy-aligned OUs, SCPs checked and simulated offline before attachment, a log-archive account with Object Lock, IAM Identity Center and a Transit Gateway hub that keeps prod and nonprod apart. Built from primitives, not Control Tower, so every guardrail is visible.

**05 · [GitOps delivery platform](projects/gitops-delivery-platform/)**
Pull-based GitOps across dev/staging/prod: an app repo whose CI opens a PR into a config repo, and Argo CD reconciling the cluster to it via an ApplicationSet. Prod rolls out as an Argo Rollouts canary gated by the same SLI used for alerting, inside sync windows.

**06 · [DevSecOps supply-chain pipeline](projects/devsecops-pipeline/)**
A reusable GitHub Actions workflow that gates a container image on secrets scanning, SAST, SCA, vulnerability scanning, SBOM generation, keyless cosign signing and a DAST baseline, behind one required gate job. Two stdlib linters keep the pipeline's own workflow files honest and expire stale exceptions.

**07 · [GCP AI pharmacy platform](projects/gcp-ai-pharmacy-platform/)**
Infrastructure for an AI-assisted pharmacy app on GCP: a private regional GKE cluster with Workload Identity, a separate AI node pool (tainted, scales to zero) alongside a steady API pool, private HA Cloud SQL and per-secret IAM. Solves the mismatch between a steady-state API workload and a bursty inference workload sharing one cluster.

**08 · [Azure AKS enterprise platform](projects/azure-aks-platform/)**
A reference AKS platform with hub-and-spoke networking and egress forced through one firewall, a private cluster with local accounts disabled, Azure RBAC, and federated workload identity for both pods and Azure DevOps pipelines — no client secret minted anywhere. Key Vault is the only secret store, reached via the Secrets Store CSI driver.

**09 · [Multi-cloud Kubernetes platform](projects/multi-cloud-kubernetes/)**
One Helm chart, one ArgoCD ApplicationSet and one ServiceAccount name deployed unmodified to EKS, AKS and GKE, with per-cloud overlays proven by test to diverge only on identity, ingress and storage. A documented, runnable comparison of where the three platforms genuinely differ (pricing, upgrade cadence, networking, logging) and where they don't.

**10 · [Serverless event-driven pipeline](projects/aws-serverless-event-driven/)**
An order-intake pipeline on API Gateway, Lambda, SQS (with a DLQ), DynamoDB and EventBridge, built stdlib-only so the handlers run end to end on a laptop against in-memory fakes. The focus is what usually breaks in event-driven systems: duplicate requests, partial failures, poison messages and tracing a request across async hops.

**11 · [SLO-driven observability](projects/observability-sre-platform/)**
Three synthetic services get SLOs defined as JSON, which a stdlib generator turns into Prometheus recording rules, multi-window multi-burn-rate alerts (Google SRE workbook), PrometheusRule CRDs, Grafana dashboards and an error-budget report. Rules pass `promtool check` and hand-written `promtool test` cases.

**12 · [Hybrid cloud fintech architecture](projects/hybrid-cloud-fintech/)**
A hybrid payments platform spanning AWS and on-prem VMware over a redundant 4-tunnel Site-to-Site VPN. A segmentation module's Terraform precondition fails validation outright if the regulated zone would ever allow `0.0.0.0/0`, and a client queues on-prem-dependent calls during a link outage and replays them.

**13 · [Cloud security & WAF automation](projects/cloud-security-waf-automation/)**
Security in three layers: preventive WAFv2 managed rules with count-then-block rollout and rate limiting, policy-as-code that gates Terraform plans in CI and reports to GitHub code scanning via SARIF, and GuardDuty/Security Hub findings routed by severity through EventBridge to page or ticket.

**14 · [FinOps cost-optimization toolkit](projects/finops-cost-optimization/)**
A reproducible cost-analysis toolkit working through the full FinOps loop — allocate, rightsize, size commitments, forecast, alert — on a seeded synthetic dataset, plus a Terraform module for cost guardrails. Follows real rightsizing and lifecycle-tuning practice without using any real figures.

**15 · [AI-powered cloud operations](projects/ai-cloud-operations/)**
A stdlib pipeline that detects log anomalies with rolling-baseline z-scores, correlates them with deploys and alerts, and optionally drafts an incident summary with an LLM. Remediation is allow-listed and proposed only — it requires explicit human approval before it's ever recorded as approved, logged to an append-only audit trail.

**16 · [CodePipeline container delivery](projects/aws-codepipeline-container-delivery/)**
An AWS-native pipeline — GitHub via CodeConnections, CodePipeline V2, CodeBuild with a Trivy gate, a manual approval, and rolling ECS Fargate deploys with the deployment circuit breaker. Targets the usual failure points: mutable tags, secrets leaking into buildspecs, and unscanned images reaching the registry.

**17 · [AWS Backup cross-region DR](projects/aws-backup-cross-region-dr/)**
Tag-selected AWS Backup plans copy every gold recovery point to a second region (and optionally account), locked down with Vault Lock and a deny-delete policy so a compromised admin can't undo it. An automated restore-testing validator and an RPO/RTO report keep the retention you review honest against the retention you deploy.

**18 · [CloudFront + S3 static delivery](projects/cloudfront-s3-static-delivery/)**
A private S3 origin read only through CloudFront via Origin Access Control, a CloudFront Function for index/redirect handling, a security headers policy, and OIDC-based GitHub Actions deploys with no stored AWS keys. A stdlib `deploy_plan.py` decides exactly what to upload, delete, invalidate and cache.

**19 · [ECS Fargate blue/green](projects/ecs-fargate-blue-green/)**
Dev/staging/prod ECS Fargate services, each behind its own ALB, deployed blue/green by CodeDeploy with a CIDR-restricted test listener, Lambda lifecycle hooks that smoke-test the new task set before and after the traffic shift, and CloudWatch alarms that trigger automatic rollback.

**20 · [EKS secrets with the CSI driver](projects/eks-secrets-store-csi/)**
A synthetic frontend on EKS reads its DB credential and API key from Secrets Manager through the Secrets Store CSI driver and EKS Pod Identity — values land as read-only tmpfs files and nothing holds them in git, the image, Helm values, Terraform state or etcd. Includes a live rotation drill and secret scanners.

## Repository layout

```
projects/<slug>/        one self-contained project: README, docs/, terraform/, kubernetes/, scripts/, tests/
.github/workflows/      per-project CI, path-filtered so only the touched project runs
docs/                   program-level docs — audit, inventory, implementation status, decisions
```

## Running a project

Each project is independent — clone the repo, `cd` into the project, and run its tests, no cloud credentials or account required:

```bash
cd projects/<project>
python3 -m unittest discover -s tests -v
```

For projects with Terraform, validate (never apply) it:

```bash
cd projects/<project>/terraform/<stack>
terraform fmt -check
terraform init -backend=false
terraform validate
```

For projects with a Helm chart:

```bash
cd projects/<project>/kubernetes/<chart>
helm lint .
helm template . | kubeconform -strict -summary
```

Each project's own `README.md` has the exact demo commands, architecture notes and what it does *not* cover (what's never been verified against a real cloud account).

## Status

All 20 projects are implemented, tested and independently re-verified — see [docs/implementation-status.md](docs/implementation-status.md) for the full verification matrix (test counts, validation evidence, and when each was last re-checked). Nothing in this repo has ever been deployed to a live cloud account.
