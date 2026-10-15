# DevOps & Cloud Architecture Examples

Working examples behind the projects on [salahuddin.wesaveall.com/projects](https://salahuddin.wesaveall.com/projects), by Muhammad Salahuddin, Senior DevOps Engineer.

Each project is labeled:

- **Production case study:** a sanitized write-up of work from my CV. The code here is a reference implementation of that pattern. Client names, domains, account IDs and figures are withheld.
- **Portfolio implementation:** code built for this portfolio on synthetic data.
- **Reference architecture:** a documented design.

Every example runs locally with no cloud account. Terraform is validated only and is never applied from this repo.

| # | Project | Label | What's in it |
|---|---|---|---|
| 01 | [Multi-region EKS disaster recovery](projects/aws-multi-region-eks-dr/) | Production case study | Two-region Terraform, Aurora Global DB, hardened Helm chart, failover orchestrator with split-brain guards, runbooks · 100 tests |
| 02 | [n8n on EKS with KEDA scale-to-zero](projects/n8n-keda-automation-platform/) | Production case study | Queue-mode n8n, KEDA Redis-list scaling, CSI secrets, verified against the real image · 96 tests |
| 04 | [Enterprise AWS landing zone](projects/aws-landing-zone/) | Production case study | Organizations, SCPs, log archive, Identity Center, TGW hub · SCP checker and simulator · 130 tests |
| 05 | [GitOps delivery platform](projects/gitops-delivery-platform/) | Production case study | Argo CD ApplicationSet, PR promotion, drift report, Rollouts canary with analysis · 85 tests |
| 06 | [DevSecOps supply-chain pipeline](projects/devsecops-pipeline/) | Production case study | Reusable GitHub Actions workflow (gitleaks, Semgrep, Trivy, SBOM, cosign, ZAP) · workflow-hardening linter · 52 tests |
| 10 | [Serverless event-driven pipeline](projects/aws-serverless-event-driven/) | Portfolio implementation | API Gateway, Lambda, SQS, DynamoDB idempotency, EventBridge · 74 tests |
| 11 | [SLO-driven observability](projects/observability-sre-platform/) | Production case study | SLOs as code → burn-rate alerts, dashboards, runbooks; promtool-tested · 79 tests |
| 13 | [Cloud security and WAF automation](projects/cloud-security-waf-automation/) | Portfolio implementation | WAF count-then-block, GuardDuty/Security Hub routing, policy-as-code with SARIF · 99 tests |
| 14 | [FinOps cost-optimization toolkit](projects/finops-cost-optimization/) | Portfolio implementation | Cost allocation, rightsizing, commitments, budget gate, Terraform guardrails · 71 tests |
| 16 | [CodePipeline container delivery](projects/aws-codepipeline-container-delivery/) | Portfolio implementation | CodeBuild with Trivy gate, immutable images, ECS with approval · 39 tests |
| 17 | [AWS Backup cross-region DR](projects/aws-backup-cross-region-dr/) | Portfolio implementation | Vault lock, cross-region copies, restore testing validator, RPO/RTO report · 118 tests |
| 18 | [CloudFront + S3 static delivery](projects/cloudfront-s3-static-delivery/) | Portfolio implementation | OAC, security headers, tested edge function, OIDC deploys · 129 tests |
| 19 | [ECS Fargate blue/green](projects/ecs-fargate-blue-green/) | Portfolio implementation | CodeDeploy canary/linear with test-listener hooks and alarm rollback · 105 tests |
| 20 | [EKS secrets with the CSI driver](projects/eks-secrets-store-csi/) | Portfolio implementation | Secrets Manager mounts via Pod Identity, live rotation drill, secret scanners · 74 tests |

Totals: 14 projects and 1,251 unit tests (stdlib Python, no dependencies). Every Terraform directory validates against `hashicorp/aws` 6.68.0. Every Helm chart passes `kubeconform -strict`, CRDs included. All 15 CI workflows pass the repository's own workflow-hardening linter: actions pinned to commit SHAs, least-privilege tokens, no persisted credentials.

The remaining projects on the website (03, 07, 08, 09, 12, 15) are documented designs without published code. See [docs/implementation-status.md](docs/implementation-status.md).

## Running a project

```bash
cd projects/<project>
python3 -m unittest discover -s tests -v
```

Each project's README lists its demo commands and how to validate its Terraform.
