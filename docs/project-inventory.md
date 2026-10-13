# Project inventory

Source of truth for content is the website's `src/data/projects.ts`; this table records the evidence basis and open questions.

| # | Slug | Evidence | CV basis | Open question for owner |
|---|---|---|---|---|
| 01 | aws-multi-region-eks-dr | Production case study | Multi-region HA + cross-region DR with automated failover; n8n DR design | Can any RTO/RPO figure be published? (Old site said "~1 min switchover" — removed until confirmed.) |
| 02 | n8n-keda-automation-platform | Production case study | Self-hosted n8n on K8s with KEDA scale-to-zero | — |
| 03 | graviton-arm64-migration | Reference architecture | Not on CV; old site showed an ARM64 ECS Fargate platform | Was there a real Graviton migration? If yes, upgrade to case study. |
| 04 | aws-landing-zone | Production case study | Multi-account AWS, VPC topologies, IAM governance | — |
| 05 | gitops-delivery-platform | Production case study | Helm + ArgoCD GitOps across dev/staging/prod | — |
| 06 | devsecops-pipeline | Production case study | SonarQube, Snyk, image scanning gates in Jenkins/GitLab/GHA | Trivy, ZAP-in-CI, SBOM, Cosign are additions in the portfolio version |
| 07 | gcp-ai-pharmacy-platform | Production case study | AI pharmacy solution on GCP (Java) | Confirm GKE vs Cloud Run and which services were actually used |
| 08 | azure-aks-platform | Reference architecture | Azure skills only, no Azure role bullet | — |
| 09 | multi-cloud-kubernetes | Reference architecture | EKS + GKE production, AKS reference | — |
| 10 | aws-serverless-event-driven | Portfolio implementation | Lambda/SQS/SNS skills | — |
| 11 | observability-sre-platform | Production case study | Prometheus/Grafana across 10+ prod envs, ELK, SLO/SLI | OpenTelemetry/Tempo are portfolio additions |
| 12 | hybrid-cloud-fintech | Production case study | Hybrid AWS + on-prem fintech, PCI-DSS/SOC2 | — |
| 13 | cloud-security-waf-automation | Portfolio implementation | ACL blocking, least privilege, rotation, SIEM | — |
| 14 | finops-cost-optimization | Portfolio implementation (synthetic data) | Rightsizing, snapshot/volume lifecycle | — |
| 15 | ai-cloud-operations | Portfolio implementation | AI log anomaly detection, LLM-assisted ops | — |
