# Program decisions

## D1 — Two repositories, not one or fifteen (2026-10-14)
The website stays in `salahuddin-profile-website` because Vercel deploys from it and moving it would change production hosting. Project code lives in this monorepo under `projects/<slug>/`. Fifteen separate repos would be fifteen sets of CI, licences and READMEs to maintain for little reviewer benefit; a project graduates to its own repo only if it becomes a substantial standalone tool.

## D2 — Evidence and status are separate labels
`evidence` (production case study / portfolio implementation / reference architecture) says where the work comes from; `status` (implemented / in progress / design) says what code exists. A production case study can still be "design" if no code is published. Both are shown on every card and page.

## D3 — No raster client diagrams
The previous PNG diagrams leaked account and network identifiers. Diagrams on the site are rendered from data (`TierDiagram`) — text-based, theme-aware, readable on mobile and by crawlers. Detailed diagrams live as Mermaid in each project's `docs/architecture.md`.

## D4 — Results only with a source
`results` stays empty unless an outcome is verifiable or reproducible. Client figures are confidential; synthetic-data outputs are labeled as such.

## D5 — GitHub links render only when the repo is public
`site.examplesRepoPublic` in the website gates every link into this repo, so the site never links to a 404 or a private repo.

## D6 — Stdlib-only Python for local demos
No dependency install needed to run tests or demos; keeps CI fast and supply-chain surface minimal.
