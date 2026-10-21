# Session handoff

## Session 5 — 2026-10-21

### Completed
- **README overhaul** (`1812138`, `a85b66c`, `595ba56`, `b4ca5d4`): rewrote the repo README from a stale 14-project table (1,251 tests) to all 20 projects with a full regression-verified test count, added a 2-3 line description per project, and added a recruiter-facing header (title, contact links, professional summary, core-skills list) sourced from the owner's current CV.
- **CV sync**: the owner supplied an updated CV showing 8+ years (was 9+ on the website and in the README header). Updated `salahuddin-profile-website`'s `resume.ts`, `layout.tsx` and `Skills.tsx` to 8+ (commit `7a11152` on `portfolio/phase-1-projects`, **not pushed/merged** — same merge-to-main restriction as before). The README here now matches the CV exactly (title, LinkedIn URL with full `-a96369137` suffix, summary, skills).
- **Full regression run**: re-ran every project's test suite individually (not trusted from docs) — all 20 pass, 1,540 tests total. The previously-recorded total of 1,474 in `implementation-status.md` was stale (predated project 09's 51 tests); corrected.
- **License added** (`56666c2`): the owner asked whether a public GitHub repo can be made "view-only, no clone/fork" — confirmed that's not possible (GitHub's `allow_forking` setting can only be changed on org-owned *private* repos; public repos are always cloneable/forkable by design, confirmed via a failed `gh api` PATCH attempt). Added an all-rights-reserved `LICENSE` instead: viewing/cloning/running tests is explicitly permitted, reuse/redistribution/AI-training use is not without permission.
- **gh CLI account**: this machine has 3 `gh` accounts logged in; switched the active one to `Salahuddin076` (the account that owns every repo in this workspace) and documented the switch in `.claude/skills/personal-profile/SKILL.md` so future sessions check/switch before any `gh api`/`gh repo`/`gh pr` call. Plain `git push`/`pull` were already unaffected (SSH alias `github-salahuddin`).

### Next
Decide whether to push/merge the website's `portfolio/phase-1-projects` branch (8+ years fix) to `main` — not done yet per the standing "never merge without explicit ask" rule. `public/resume.pdf` still has no source file in the repo to regenerate from; confirm what figure it currently shows and whether it needs manual updating to match 8+.

## Session 4 — 2026-10-19

### Completed
Owner approved the blockers pending since session 1:
- **K1/K3**: website merged to `main` and pushed (production deploy on Vercel); examples repo confirmed already public on GitHub, `examplesRepoPublic` flipped to `true`.
- **K4**: experience figure changed 7+ → 9+ years across the website (`resume.ts`, `layout.tsx` metadata, `Experience.tsx`, `Skills.tsx`). `public/resume.pdf` is a static binary with no source in the repo and still says 7+ — flagged to the owner to update separately.
- **K2**: `thedusttest-iac`'s committed prod `tfplan` (a zip bundling `tfstate`/`tfstate-prev` with real AWS account IDs and a Secrets Manager `secret_string`) was purged from all git history with `git-filter-repo`, force-pushed, and the repo flipped to private. The actual secret value couldn't be inspected (agent sandbox blocked reading credential material from the state file), so the owner should confirm whether it needs rotating.
- **Project 03 (graviton-arm64-migration) implemented** (`77eec05`): built by a subagent, independently re-verified (45 tests, 3 terraform dirs validate, helm lint + kubeconform strict for stable and canary, workflow linter 0/0), website page updated (`c9e8534`). ECS Fargate was dropped from the stack list — only EKS node groups were built, since Fargate IaC already exists in project 19 and wasn't part of this project's scheduling-based migration story.
- **Project 15 (ai-cloud-operations) implemented** (`51755b3`): a pure-stdlib Python pipeline — rolling-baseline z-score anomaly detection, deploy/alert correlation, a no-op-default LLM provider interface (zero network calls/API keys unless a caller wires one in), redaction before any external call, and an allow-listed remediation flow with an append-only audit log. Independently re-verified: 66 tests, workflow linter 0/0, and the allow-list/append-only/no-op guarantees confirmed by reading `aiops/audit.py`, `aiops/remediation.py` and `aiops/llm.py` directly rather than trusting the build agent's description. Website page updated (`a288f1f`); Slack/email adapters dropped from the stack list since only a CLI was built.
- **Project 07 (gcp-ai-pharmacy-platform) implemented** (`ad825e5`): private regional GKE with Workload Identity, separate API/AI node pools (AI pool tainted, scales to zero), private Cloud SQL (HA), per-secret IAM, project-level audit logging. First pull of the `google` provider on this machine (now cached). 41 tests, 7 terraform dirs validate, helm/kubeconform clean. Website updated (`877f1ad`).
- **Project 08 (azure-aks-platform) implemented** (`00e8a9e`): hub-and-spoke networking with forced tunneling through Azure Firewall, private AKS with local accounts disabled, Azure RBAC + policy add-on, federated-credential workload identity for pods and the Azure DevOps pipeline (no client secrets anywhere). First pull of `azurerm`/`azuread` (now cached). 46 tests, 7 terraform dirs validate. Website updated (`319f738`).
- **Project 09 (multi-cloud-kubernetes) implemented** (`a9b6256`): one Helm chart deployed to EKS/AKS/GKE via three overlays proven (by test) to diverge only on identity/ingress/storage; a Terraform identity-bindings module per cloud instead of three more cluster stacks; one ArgoCD ApplicationSet; a self-validating comparison doc. This build's subagent was cut off mid-task by the account's weekly usage limit (see K14) after producing everything except tests/README/workflow — I finished those myself and independently verified the rest by reading the source. 51 tests, 2 terraform dirs validate, helm/kubeconform clean for all 3 overlays, ArgoCD manifests valid against the community CRD catalog. Website updated (`ad239fa`).
- **Project 12 (hybrid-cloud-fintech) implemented** (`8f8e557`): redundant Site-to-Site VPN (4 tunnels), a segmentation module whose Terraform precondition fails validation outright if the regulated zone would ever allow `0.0.0.0/0`, a graceful-degradation client that queues on-prem-dependent calls to an outbox during a link outage and replays them, and one Ansible baseline role applied identically to AWS and on-prem inventory. 40 tests, 3 terraform dirs validate, ansible-lint "production" profile 0/0. Website updated (`0eb09a0`).

**All 20 projects are now implemented.** 1,474 tests total across the portfolio (not re-run as one full regression since the last several additions — see `implementation-status.md`).

Also resolved this session: K1 (website deployed to `main`), K2 (`thedusttest-iac`'s leaked tfplan purged from git history, repo made private), K3 (examples repo confirmed public, linked from the site), K4 (experience figure 7+ → 9+ across the site). Two loose ends remain for the owner: `public/resume.pdf` still says 7+ (no source file in the repo to regenerate from), and whether to rotate whatever secret was in `thedusttest-iac`'s old (now-purged) state file.

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
