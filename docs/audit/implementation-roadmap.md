# Implementation roadmap

Ordered by value to a reviewer ÷ effort. A project counts as done only when its code, docs and tests pass locally (see `../implementation-status.md`).

| Phase | Scope | State |
|---|---|---|
| 0 | Audit repo, site, CV, GitHub | ✅ done |
| 1 | Decisions: repo split, taxonomy, evidence labels, slugs | ✅ done (`../architecture/decisions.md`) |
| 2–3 | Website: multi-page, project data model, gallery with search/filter, detail template, SEO basics, 404 | ✅ done, not deployed |
| 4a | Project 14 FinOps toolkit (fully local, testable) | 🔄 in progress |
| 4b | Project 02 n8n + KEDA (Helm values, manifests, KEDA ScaledObject, Terraform for EKS add-ons) | next |
| 4c | Project 10 serverless (Python Lambdas with idempotency, unit tests, Terraform) | next |
| 4d | Project 01 multi-region DR (Terraform two-region root, runbook) | |
| 5–7 | 15 AI ops (offline), 06 DevSecOps (reusable workflow), 05 GitOps, 11 SRE, 04 landing zone, 07 GCP, 08 Azure, 09 multi-cloud, 03 Graviton, 12 hybrid, 13 security | |
| 8 | GitHub profile README, repo descriptions/topics, publish examples repo (needs approval) | |
| 9 | Light theme, OG image, security headers, FAQ section, Lighthouse | |
| 10 | Full QA, security review | |
| 11 | Website CI, deployment/rollback guide, release (needs approval) | |

Tooling to install for later phases: `helm`, `kubeconform`, `tflint`, `trivy`/`checkov` (brew). Optional: `bun` + gstack for browser QA.
