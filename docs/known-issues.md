# Known issues

| # | Issue | Impact | Owner action |
|---|---|---|---|
| K1 | Live site still serves the confidential diagrams (S1–S3 in `audit/initial-audit.md`) until the website is redeployed | Account/VPC IDs and client names publicly visible | Approve website push/deploy |
| K2 | `thedusttest-iac` public repo has a committed prod `tfplan` | Possible plaintext secrets | Inspect, remove, consider making private, rotate if needed |
| K3 | This repo is not public, so project pages show "will be linked once published" instead of GitHub links | Reviewers can't see code yet | Approve publishing, then set `examplesRepoPublic: true` in the website's `src/lib/site.ts` |
| K4 | Experience number: CV says 7+, dates give ~9 years | Underselling | Decide 7+ vs 9+ |
| K5 | gstack not installed (needs bun); agent-skills not installed as plugin | Browser QA done with headless Chrome/CDP instead | Optional: `brew install oven-sh/bun/bun`, then follow gstack README; `/plugin marketplace add addyosmani/agent-skills` |
| K6 | No light theme yet; no OG image; no security headers on the website | Prompt requirements unmet | Phase 9 |
| K7 | helm, kubeconform, tflint, trivy not installed locally | K8s/Helm validation limited | `brew install helm kubeconform tflint trivy` |
