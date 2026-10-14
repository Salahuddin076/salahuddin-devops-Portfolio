# Known issues

| # | Issue | Impact | Owner action |
|---|---|---|---|
| K1 | Live site still serves the confidential diagrams (S1–S3 in `audit/initial-audit.md`) until the website is redeployed | Account/VPC IDs and client names publicly visible | Approve website push/deploy |
| K2 | `thedusttest-iac` public repo has a committed prod `tfplan` | Possible plaintext secrets | Inspect, remove, consider making private, rotate if needed |
| K3 | This repo is not public, so project pages show "will be linked once published" instead of GitHub links | Reviewers can't see code yet | Approve publishing, then set `examplesRepoPublic: true` in the website's `src/lib/site.ts` |
| K4 | Experience number: CV says 7+, dates give ~9 years | Underselling | Decide 7+ vs 9+ |
| K5 | gstack + bun are now installed (session 2) but not yet used; agent-skills not installed as plugin | QA so far via headless Chrome/CDP | Use `/browse` / `/qa` next session; optional `/plugin marketplace add addyosmani/agent-skills` |
| K6 | No OG image; CSP needs `'unsafe-inline'` for scripts (static site, no nonces) | Minor | Phase 9: add OG image; revisit CSP hashes |
| K7 | helm, kubeconform, tflint, trivy not installed; `brew install helm kubeconform` timed out (slow network) | Blocks proper manifest validation for Project 02 | Run `brew install helm kubeconform tflint trivy` in a terminal |
| K8 | AWS provider 6.x download takes ~13 min here | Slow first validate | Keep `TF_PLUGIN_CACHE_DIR=~/.terraform.d/plugin-cache` (now holds 6.68.0) |
