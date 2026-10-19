# Session handoff

## Session 4 — 2026-10-19

### Completed
Owner approved the blockers pending since session 1:
- **K1/K3**: website merged to `main` and pushed (production deploy on Vercel); examples repo confirmed already public on GitHub, `examplesRepoPublic` flipped to `true`.
- **K4**: experience figure changed 7+ → 9+ years across the website (`resume.ts`, `layout.tsx` metadata, `Experience.tsx`, `Skills.tsx`). `public/resume.pdf` is a static binary with no source in the repo and still says 7+ — flagged to the owner to update separately.
- **K2**: `thedusttest-iac`'s committed prod `tfplan` (a zip bundling `tfstate`/`tfstate-prev` with real AWS account IDs and a Secrets Manager `secret_string`) was purged from all git history with `git-filter-repo`, force-pushed, and the repo flipped to private. The actual secret value couldn't be inspected (agent sandbox blocked reading credential material from the state file), so the owner should confirm whether it needs rotating.
- **Project 03 (graviton-arm64-migration) implemented** (`77eec05`): built by a subagent, independently re-verified (45 tests, 3 terraform dirs validate, helm lint + kubeconform strict for stable and canary, workflow linter 0/0), website page updated (`c9e8534`). ECS Fargate was dropped from the stack list — only EKS node groups were built, since Fargate IaC already exists in project 19 and wasn't part of this project's scheduling-based migration story.

**State now: 15 implemented, 5 design-only (07, 08, 09, 12, 15).**

### Next
See `docs/next-session-prompt.md` (being updated now).

## Session 3, continued — 2026-10-15

Three more design-only projects were implemented and independently verified: **02** n8n + KEDA (`cff364a`), **11** SLO-driven observability (`da44c44`) and **05** GitOps (`210fe81`). The website pages are updated, the home page features nine implemented projects, and an OG share image and an FAQ section were added (`25eb40c`).

There are now **14 implemented and 6 design-only projects** (03, 07, 08, 09, 12, 15).

Incidents K12 and K13 (see `known-issues.md`) led to tighter build-agent briefs:
- no cloud CLIs;
- quoted heredocs only;
- no machine-wide Docker cleanup.

Nothing from this continuation is pushed yet.

## Session 3 — 2026-10-14

### Completed
At the owner's request, 10 more projects were built: five existing designs got code, and five new projects were added. Each one was built by a subagent, **independently re-verified**, and committed on its own.

| Commit | Project |
|---|---|
| `1d62afe` | 10 serverless event-driven |
| `3310820` | 16 CodePipeline container delivery *(new)* |
| `338f148` | 13 cloud security + WAF |
| `bbd802c` | 04 landing zone |
| `115df80` | 17 AWS Backup cross-region DR *(new)* |
| `f87afe0` | 18 CloudFront + S3 delivery *(new)* |
| `98226ec` | 19 ECS Fargate blue/green *(new)*. Reworked before commit to one ALB per environment, after the agent found that CodeDeploy is documented only with listener default actions. |
| `918d5c4` | 06 DevSecOps pipeline |
| `f5a64c9` | Hardened all workflows. Project 06's linter found 39 errors and 46 warnings in the other workflows; all actions are now pinned to SHAs and every checkout sets `persist-credentials: false`. |
| `25c61b5` | 01 multi-region EKS DR |
| `9f9ba4f` | 20 EKS Secrets Store CSI *(new)* |
| `8cd0fa2` | Fixed a project-18 test that was stale after SHA pinning. Found by the full regression run. |

**State now:**
- **Examples repo:** 11 implemented projects, 991 tests, all green.
- **Website:** 20 project pages; 11 are marked implemented, and the home page features only implemented ones.

Website commits on `portfolio/phase-1-projects` this session: from `7ecdb4b` through `6d7640d`, one per project, plus `f1c05a1` (featured swap).

### Not pushed
Both repos have unpushed local commits. Pushing the website branch creates a Vercel preview; only a merge to `main` deploys production.

### Decisions
- New projects 16–20 are labeled portfolio implementations (owner's choice) and numbered in the order they were completed.
- Production-case-study projects 01, 04 and 06 now have code. Their basis line says the code is a synthetic reference implementation.

### Incidents
K10 in `known-issues.md`: one agent ran `terraform apply` on a provider-less scratch config. There was no AWS impact, and the briefs were tightened afterwards.

### Next
See `next-session-prompt.md`.

## Session 2 — 2026-10-14 (resumed after two session restarts)

### Completed
- **Project 14 fully verified:** `terraform validate` passes for the module and the example (aws 6.68.0). The site status is flipped to `implemented`.
- **Bug fix (`1e33d18`):** the Services section still referenced a deleted diagram, leaving a broken image on the home page. Session 1's crawler only checked `href`s; the new smoke test also checks `src`.
- **Light theme (`dda3762`):** tokenized colors, OS-preference default, persisted toggle, no flash on load.
- **Security headers + CI (`fc83464`):**
  - CSP, nosniff, Referrer-Policy, X-Frame-Options and Permissions-Policy in `next.config.ts`.
  - `.github/workflows/ci.yml` runs lint → build → typecheck → `scripts/smoke.mjs`.
  - The smoke script fails on broken links/assets, missing headers or a wrong 404, and was negative-tested against the live site.

### Website branch state
`portfolio/phase-1-projects`: `97123d5` → `1e33d18` → `dda3762` → `fc83464`. **Not pushed.** Pushing to `main` deploys to production on Vercel.

### Notes for next session
- Background jobs die when the session restarts. Run long commands (terraform init, brew) in the foreground with `timeout: 600000`, or expect to re-run them.
- The scratchpad is wiped on restart, so the CDP QA scripts are gone. Use gstack `/browse` (now installed) instead.
- helm/kubeconform are still missing (the brew install timed out). Install them before Project 02.

## Session 1 — 2026-10-14

### Completed
- **Phase 0 audit** → `docs/audit/initial-audit.md`, `portfolio-gap-analysis.md`, `implementation-roadmap.md`.
- **Decisions** → `docs/architecture/decisions.md` (two-repo split, evidence vs status labels, no raster client diagrams, results only with source).
- **Website** (`../salahuddin-profile-website`, branch `portfolio/phase-1-projects`, commit `97123d5`, **not pushed**):
  - `/projects` gallery with search and category filters.
  - 15 static project pages from `src/data/projects.ts`, each with overview, problem, solution, data-driven diagram, failure path, stack, implementation, security, reliability, cost, results, code and lessons sections.
  - Sitemap, robots, canonicals, JSON-LD and a 404 page.
  - Removed 4 diagrams; 2 of them leaked account/VPC IDs and client names.
- **Project 14 FinOps toolkit** in `projects/finops-cost-optimization/`, built by a subagent and independently re-verified.
- Program docs: `CLAUDE.md`, `README.md`, inventory, status, testing, known issues, next-session prompt.
- Workspace skill `personal-profile` updated for the new project model.

### Commits
- Website: `97123d5` on `portfolio/phase-1-projects`. A follow-up commit flips Project 14 to `implemented`, after validation.
- Examples repo: initial commit (see `git log`). Not pushed.

### Tests
See `docs/testing-status.md`. Website: tsc, lint, build, route smoke, link crawl, responsive overflow at 3 widths all pass. FinOps: 71 tests, report, budget gate, fmt pass.

### Blockers needing owner approval
1. Push and deploy the website branch. This is the only way to remove the leaked diagrams from the live site (K1).
2. Inspect and clean the public `thedusttest-iac` `tfplan` (K2).
3. Publish this repo, then set `examplesRepoPublic: true` (K3).
4. Decide 7+ vs 9+ years (K4).
5. Answer the open questions in `docs/project-inventory.md`.

### Notes
- gstack appeared as an available skill late in the session (it had not been installed at the start). Use it for the next browser QA pass. Until now QA used headless Chrome over CDP; that script is not in the repo.
- First `terraform init` downloads the AWS provider slowly (minutes). Set `TF_PLUGIN_CACHE_DIR`.
- In zsh, don't name a loop variable `path`: it overwrites `PATH`.

### Next
See `docs/next-session-prompt.md`.
