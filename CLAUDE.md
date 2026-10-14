# salahuddin-devops-Portfolio

Architecture-examples monorepo for Muhammad Salahuddin's DevOps / cloud portfolio. The website that presents these projects is a **separate repo**: `../salahuddin-profile-website` (Next.js 16, deployed on Vercel to salahuddin.wesaveall.com).

**Start every session by reading `docs/session-handoff.md`.**

## Layout
- `projects/<slug>/` — one self-contained project each (README, docs/, terraform/, kubernetes/, scripts/, tests/ — only what the project needs). Slugs must match `src/data/projects.ts` in the website repo.
- `.github/workflows/<slug>.yml` — per-project CI with `paths:` filters (workflows only run from the repo root).
- `docs/` — program-level docs: audit, inventory, status, decisions, handoff.

## Rules
- Never `terraform apply`/`plan` against a real account, never use real credentials, never create paid resources. Validation only: `terraform fmt -check`, `terraform init -backend=false && terraform validate`.
- Synthetic names and documentation-safe values only (`example.com`, `203.0.113.0/24`, `arn:aws:s3:::example-*`). No client names, account IDs, domains or real figures.
- Every project is labeled *production case study* / *portfolio implementation* / *reference architecture*, and a project is "implemented" only when its tests and validation pass locally. Update `docs/implementation-status.md` and the website's `projects.ts` `status` together.
- Prices and savings are illustrative unless sourced; say so.
- Don't push, publish the repo, or deploy the website without the owner's explicit approval.
- Every workflow must pass `python3 projects/devsecops-pipeline/policy/check_workflows.py --uri-base . .github/workflows --fail-on warning` (actions pinned to SHAs, `persist-credentials: false`, top-level `contents: read`).
- Build projects with one subagent at a time in this repo, and re-run its checks yourself before committing.

## Commands (per project)
- Python: `python3 -m unittest discover -s tests -v` (stdlib only; pytest isn't installed)
- Terraform: `export TF_PLUGIN_CACHE_DIR=~/.terraform.d/plugin-cache` (aws 6.68.0 cached; otherwise ~13 min download), copy an existing `.terraform.lock.hcl` in before the first init, then `terraform fmt -check -recursive && terraform -chdir=<dir> init -backend=false && terraform -chdir=<dir> validate`
- Kubernetes: `helm lint` and `helm template … | kubeconform -strict -summary -cache <dir>` (helm and kubeconform are installed)

## Skills
Addy Osmani skills are cloned at `../agent-skills/skills/` — read only the relevant `SKILL.md` per phase (e.g. `test-driven-development`, `security-and-hardening`, `documentation-and-adrs`). gstack is installed — use `/qa` for browser QA of the website.

## Docs
`docs/architecture/overview.md`, `docs/architecture/decisions.md`, `docs/project-inventory.md`, `docs/implementation-status.md`, `docs/testing-status.md`, `docs/known-issues.md`, `docs/next-session-prompt.md`.
