# Testing status

Last run: 2026-10-14 (sessions 1–3). Only commands that actually completed are listed.

## Website (`salahuddin-profile-website`, branch `portfolio/phase-1-projects`)

| Check | Command | Result |
|---|---|---|
| Type check | `npx tsc --noEmit` | ✅ pass |
| Lint | `npm run lint` | ✅ pass (0 problems) |
| Build | `npm run build` | ✅ pass, 22 static pages (home, /projects, 15 project pages, sitemap, robots, 404) |
| Route smoke test | curl against `next start` | ✅ 200 for /, /projects, detail pages, robots, sitemap, resume.pdf; 404 for unknown slug and the removed diagram |
| Internal link crawl | Python crawler from `/` | ✅ 19 URLs, no broken internal links |
| SEO tags | curl + grep | ✅ unique title, canonical and og:title per project page; sitemap has 17 URLs; robots references sitemap |
| Responsive overflow | Headless Chrome via CDP, 390 / 820 / 1440 px, 5 pages | ✅ no horizontal overflow (scrollWidth = viewport) |
| Visual review | Screenshots of /projects (desktop) and a detail page (mobile) | ✅ reviewed |
| Asset crawl (href + src) | Python crawler, then `npm run smoke` | ✅ 17 pages, 70 assets, 0 broken (session 1's crawler missed a broken `<img>` in Services — fixed in `1e33d18`) |
| Smoke script negative test | `node scripts/smoke.mjs https://salahuddin.wesaveall.com` | ✅ fails as expected (live site lacks headers, robots, sitemap) |
| Security headers | `curl -I` | ✅ CSP, nosniff, Referrer-Policy, X-Frame-Options, Permissions-Policy present |
| Console / CSP violations | CDP: load 4 pages, click theme toggle and a filter | ✅ none (only the intended 404) |
| Light theme | CDP screenshots, desktop + mobile | ✅ reviewed |
| Lighthouse / axe | — | ⏳ not run yet |
| Keyboard walkthrough | — | ⏳ not run yet (filters are `<button aria-pressed>`, cards use one link with a stretched hit area) |

## Examples repo

Each project was built by a subagent and then **re-verified independently** by running its commands again before commit. On 2026-10-14 a full regression run executed all 11 suites together.

| Project | Unit tests | Other checks re-run |
|---|---|---|
| 01 aws-multi-region-eks-dr | 100 OK | terraform validate ×5; `helm lint` ×2; `helm template \| kubeconform -strict` 11/11 valid for primary and DR values |
| 04 aws-landing-zone | 130 OK | `check_scps.py` passes shipped / fails bad fixtures; `cidr_plan.py`; terraform validate ×10 |
| 06 devsecops-pipeline | 52 OK | workflow lint 0/0 over all 12 workflows; `trivyignore_check.py`; one action SHA spot-checked against GitHub |
| 10 aws-serverless-event-driven | 74 OK | `local_demo.py` exit 0; terraform validate ×2 |
| 13 cloud-security-waf-automation | 99 OK | `check_plan.py` compliant exit 0 / non-compliant exit 1 (7 findings); WAF log summary; terraform validate ×3 |
| 14 finops-cost-optimization | 71 OK | report end to end; budget gate exit 3 on breach; terraform validate ×2 |
| 16 aws-codepipeline-container-delivery | 39 OK | buildspec lint passes real / fails 8 bad; terraform validate ×2 |
| 17 aws-backup-cross-region-dr | 118 OK | policy check pass/fail; RPO report exit 1 on the planted breach; terraform validate ×2 |
| 18 cloudfront-s3-static-delivery | 129 OK | header check pass/fail; deploy job confirmed `if: false`; terraform validate ×3 |
| 19 ecs-fargate-blue-green | 105 OK | policy lint pass/fail; no listener rules remain; terraform validate ×6 |
| 20 eks-secrets-store-csi | 74 OK | rotation drill PASS (~0.5 s); detector 0 findings; manifest scan; kubeconform strict 6/6 incl. SecretProviderClass CRD schema; terraform validate ×2 |
| **Total** | **991 OK** | The regression run found one stale test in project 18 after SHA pinning; it was fixed in `8cd0fa2` and re-run green |

Not run anywhere: live AWS acceptance (by policy), and GitHub Actions (the repo has never run CI on GitHub).
