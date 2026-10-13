# Initial audit — 2026-10-14

## Repositories

| Repo (local path) | Remote | State |
|---|---|---|
| `salahuddin-profile-website/` | `Salahuddin076/salahuddin-profile-website` (not public) | Next.js 16.3.3, React 19.2, Tailwind 4, TypeScript. Single page, ~1.3k lines. Deployed on **Vercel** to `salahuddin.wesaveall.com` (response headers: `server: Vercel`, `x-nextjs-prerender`). No CI, no tests, no `.vercel/` locally (project linked in the Vercel dashboard). |
| `salahuddin-devops-Portfolio/` (this repo) | `Salahuddin076/salahuddin-devops-Portfolio` | Empty at audit time — no commits. |
| `thedusttest-iac` (GitHub only) | public | Terraform for a client application. **Contains a committed `environments/prod/tfplan`** — see Security. |
| Other public repos | `agent-skills` (fork), `replica-skill` (fork), `crypto`, `Salahuddin`, `github` | Not portfolio material; old or forked. |

GitHub profile: no name, bio, website or profile README; 6 public repos; nothing pinned that represents DevOps work.

## Live website (salahuddin.wesaveall.com)

- Single scrolling page: hero, services, about, skills, experience, projects (5 cards), education, contact.
- Title and meta description present. **Missing:** canonical URL, `robots.txt` (404), `sitemap.xml` (404), structured data, per-page metadata (only one page exists), Open Graph image.
- Dark-only theme; `prefers-reduced-motion` already respected; skip link present; good contrast work from earlier commits.
- Resume PDF served at `/resume.pdf`.
- HSTS set by Vercel. No CSP or other security headers configured.

## Security / confidentiality findings

| # | Severity | Finding | Action taken | Needs owner |
|---|---|---|---|---|
| S1 | **High** | Live site serves `architecture/colaraz-lms-architecture.png`, which shows a **real AWS account ID, VPC ID, subnet IDs and client domains**. | Removed from the website repo locally (not yet deployed). | Approve deploy. File stays in git history and in any caches until redeployed; consider whether the client should be told. |
| S2 | **High** | Live site serves `architecture/aws-landing-zone-architecture.png`: a client's ("GameCheck") diagram authored by a third party, with public IPs, a third-party AWS account ID and resource names. | Removed locally. | Approve deploy. |
| S3 | Medium | `architecture/n8n-dr-architecture.png` exposes internal bucket/ingress naming of a client environment and an unverified "~1 min switchover" claim. | Removed locally; replaced by a sanitized, text-based diagram on the project page. | — |
| S4 | **High (unverified)** | Public repo `thedusttest-iac` contains `environments/prod/tfplan`. Terraform plan files can contain resolved variable values, including secrets, in plaintext. Contents were **not** inspected (scan was blocked by tool permissions). | None — outside this repo. | Owner should inspect, remove the file, make the repo private or sanitized, and rotate any secret that appears in it. Removing the file does not remove it from history. |
| S5 | Low | Website has no security headers beyond HSTS. | Planned (Phase 9). | — |

## CV review

- Dates: May 2017 – present ≈ **9 years 5 months**. The CV and site say **7+**. Kept as 7+ (it is true) — **owner should decide** whether to publish 9+.
- The CV names client products (AutoLeap, Fun Social, HairCut, ScoutPro, The Dust Test, HomeGlance, OneLoad, OneZapp). They stay in the Experience section (already public in the CV) but are **not** used on project pages, which are anonymized.
- No certifications listed; none are claimed anywhere.

## Tooling

- Addy Osmani `agent-skills`: user's fork is cloned at `../agent-skills/`. Not installed as a Claude Code plugin (requires `/plugin marketplace add addyosmani/agent-skills`, an interactive command). Skills are read on demand from the local clone.
- gstack: **not installed**. It requires `bun` (not installed), and cloning it was blocked by the session's permission classifier. Browser QA was done with headless Chrome over the DevTools protocol instead.
- Local: Node 24, Python 3.14 (no pytest), Terraform 1.14.8, kubectl, Docker. Missing: helm, kubeconform, tflint, trivy, checkov.
