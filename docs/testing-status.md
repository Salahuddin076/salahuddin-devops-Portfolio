# Testing status

Last run: 2026-10-14 (session 1). Only commands that actually completed are listed.

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
| Lighthouse / axe | — | ⏳ not run yet |
| Keyboard walkthrough | — | ⏳ not run yet (filters are `<button aria-pressed>`, cards use one link with a stretched hit area) |

## Examples repo

| Project | Check | Result |
|---|---|---|
| 14 finops-cost-optimization | `python3 -m unittest discover -s tests` | ✅ 71 tests OK (re-run independently after the build agent) |
| | `python3 -m finops report --input sample-data --budget 6500 --out … --html` | ✅ exit 0, writes report.md / report.html / summary.json |
| | `python3 -m finops budget --budget 6000` | ✅ exit 3 (breach) as designed |
| | `terraform fmt -check -recursive` | ✅ pass |
| | `terraform validate` (module + example, aws provider 6.x) | see implementation-status.md |
| | GitHub Actions workflow | ⏳ never run on GitHub (repo not pushed) |
| | Live AWS acceptance | ❌ intentionally not run (no cloud access by policy) |
