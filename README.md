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
