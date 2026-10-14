# Implementation status: completion matrix

A project is ✅ only when its code, docs and tests pass locally **and** I have re-run them independently. A page on the website does not count.

| # | Project | Label (website) | Code + docs | Tests | Terraform / K8s validation | Overall |
|---|---|---|---|---|---|---|
| 01 | aws-multi-region-eks-dr | Production case study | ✅ | 100 ✅ | 5 dirs validate · helm lint + kubeconform strict 11/11 (both regions) | **Implemented** |
| 02 | n8n-keda-automation-platform | Production case study | page only | — | — | Design |
| 03 | graviton-arm64-migration | Reference architecture | page only | — | — | Design |
| 04 | aws-landing-zone | Production case study | ✅ | 130 ✅ | 10 dirs validate | **Implemented** |
| 05 | gitops-delivery-platform | Production case study | page only | — | — | Design |
| 06 | devsecops-pipeline | Production case study | ✅ | 52 ✅ | workflow lint 0/0; scanners run locally via Docker | **Implemented** |
| 07 | gcp-ai-pharmacy-platform | Production case study | page only | — | — | Design |
| 08 | azure-aks-platform | Reference architecture | page only | — | — | Design |
| 09 | multi-cloud-kubernetes | Reference architecture | page only | — | — | Design |
| 10 | aws-serverless-event-driven | Portfolio implementation | ✅ | 74 ✅ | 2 dirs validate | **Implemented** |
| 11 | observability-sre-platform | Production case study | page only | — | — | Design |
| 12 | hybrid-cloud-fintech | Production case study | page only | — | — | Design |
| 13 | cloud-security-waf-automation | Portfolio implementation | ✅ | 99 ✅ | 3 dirs validate | **Implemented** |
| 14 | finops-cost-optimization | Portfolio implementation | ✅ | 71 ✅ | 2 dirs validate | **Implemented** |
| 15 | ai-cloud-operations | Portfolio implementation | page only | — | — | Design |
| 16 | aws-codepipeline-container-delivery | Portfolio implementation | ✅ | 39 ✅ | 2 dirs validate · Docker image built and run | **Implemented** |
| 17 | aws-backup-cross-region-dr | Portfolio implementation | ✅ | 118 ✅ | 2 dirs validate | **Implemented** |
| 18 | cloudfront-s3-static-delivery | Portfolio implementation | ✅ | 129 ✅ | 3 dirs validate · edge function run under Node | **Implemented** |
| 19 | ecs-fargate-blue-green | Portfolio implementation | ✅ | 105 ✅ | 6 dirs validate · arm64 image built and run | **Implemented** |
| 20 | eks-secrets-store-csi | Portfolio implementation | ✅ | 74 ✅ | 2 dirs validate · kubeconform strict incl. CRD schema | **Implemented** |

**11 implemented, 9 design.** In total: 991 tests, and a full regression run on 2026-10-14 passed after one test fix (`8cd0fa2`). Nothing has been deployed to a cloud account; every project's README lists what remains unverified against real AWS.

Projects 16–20 were added in session 3. At the owner's request they are all labeled portfolio implementations, and they are numbered in the order they were completed.

## Website features

| Feature | State |
|---|---|
| Home with featured (implemented-only) projects | ✅ |
| Projects gallery with search and filters | ✅ |
| 20 project detail pages | ✅ |
| Sitemap, robots, canonicals, OG, JSON-LD | ✅ (no OG image yet) |
| 404 page | ✅ |
| Light/dark theme | ✅ |
| Security headers | ✅ |
| Website CI (lint, build, typecheck, smoke) | ✅ written, never run on GitHub |
| Domain pages (AWS, GCP, Azure, …) | ⏳ |
| Technical blog | ⏳ |
| FAQ (AEO) | ⏳ |
| Deployed | ❌ awaiting approval (merge to `main`) |
