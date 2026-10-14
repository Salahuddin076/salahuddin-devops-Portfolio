# Known issues

| # | Issue | Impact | Owner action |
|---|---|---|---|
| K1 | Live site still serves the confidential diagrams (S1–S3 in `audit/initial-audit.md`) until the website is redeployed | Account/VPC IDs and client names publicly visible | Approve website push/deploy |
| K2 | `thedusttest-iac` public repo has a committed prod `tfplan` | Possible plaintext secrets | Inspect, remove, consider making private, rotate if needed |
| K3 | This repo is not public, so project pages show "will be linked once published" instead of GitHub links | Reviewers can't see code yet | Approve publishing, then set `examplesRepoPublic: true` in the website's `src/lib/site.ts` |
| K4 | Experience number: CV says 7+, dates give ~9 years | Underselling | Decide 7+ vs 9+ |
| K5 | gstack is installed but not yet used for QA; agent-skills is not installed as a plugin | QA so far via headless Chrome/CDP | Use `/qa` next session |
| K6 | No OG image; CSP needs `'unsafe-inline'` for scripts (static site, no nonces) | Minor | Phase 9: add OG image; revisit CSP hashes |
| K7 | ~~helm, kubeconform missing~~ resolved in session 3 (helm 4.3.0, kubeconform 0.8.0; install with `HOMEBREW_NO_AUTO_UPDATE=1`). tflint, trivy and checkov are still not installed locally | — | Optional |
| K8 | AWS provider 6.x download takes ~13 min here | Slow first validate | Keep `TF_PLUGIN_CACHE_DIR=~/.terraform.d/plugin-cache` (now holds 6.68.0) |
| K9 | No project has been deployed. Each README lists the AWS behaviours that are unverified (IAM sufficiency, a few API semantics, add-on config keys) | Expected for a no-spend portfolio | Sandbox-account acceptance if the owner wants it |
| K10 | Session 3: the Project 04 build agent ran `terraform apply` once on a provider-less scratch config (no resources, no credentials) to evaluate expressions. Nothing touched AWS, and the scratch dir and state were confirmed deleted | Rule breach, no impact | Later briefs forbid apply/plan/destroy outright and point to `terraform console` |
| K11 | Project 20's README test pins the detector's "files scanned" count, so adding or removing a file in that project changes it | Minor test brittleness | Update the README sample when files change |
| K12 | Session 3: while editing a doc, the Project 02 build agent used an unquoted heredoc whose text contained `$(aws secretsmanager get-secret-value --secret-id n8n/redis-auth …)`, so the shell ran it. `~/.aws` exists on this machine, so the call may have reached AWS with the default profile. It was read-only, for a secret name that likely doesn't exist; it hung and was killed. Nothing could have been created or changed | Possible single read-only API call | Owner can check CloudTrail for a `GetSecretValue` on `n8n/redis-auth` around 2026-10-14. Later briefs require quoted heredocs (`<<'EOF'`) |
