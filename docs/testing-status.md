# Testing status

Last run: 2026-10-14 (sessions 1–2). Only commands that actually completed are listed.

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

| Project | Check | Result |
|---|---|---|
| 14 finops-cost-optimization | `python3 -m unittest discover -s tests` | ✅ 71 tests OK (re-run independently after the build agent) |
| | `python3 -m finops report --input sample-data --budget 6500 --out … --html` | ✅ exit 0, writes report.md / report.html / summary.json |
| | `python3 -m finops budget --budget 6000` | ✅ exit 3 (breach) as designed |
| | `terraform fmt -check -recursive` | ✅ pass |
| | `terraform init -backend=false && terraform validate` (module + example) | ✅ Success, hashicorp/aws 6.68.0 |
| | GitHub Actions workflow | ⏳ never run on GitHub (repo not pushed) |
| | Live AWS acceptance | ❌ intentionally not run (no cloud access by policy) |
