# Cost

> All figures are **illustrative estimates**, not measurements from a real
> run. This workflow has not run on GitHub yet (it is not pushed). GitHub
> Actions is free for public repositories on standard hosted runners. Private
> repositories consume the plan's included minutes, billed per minute rounded
> up per job; check the current GitHub pricing page before budgeting.

## Runner minutes per run (estimate)

Each job is billed separately, rounded up to the minute, so ten small jobs
cost more than one large one. The estimates assume `ubuntu-latest`, a warm
Trivy cache, and the tiny demo app.

| Job | Est. minutes | Main cost driver |
|---|---|---|
| policy (caller) | 1 | setup-python, 52 unit tests |
| secrets-scan | 1 | full `fetch-depth: 0` clone, gitleaks image pull |
| sast | 2–3 | `pip install semgrep`, ruleset download |
| sca | 1 | Trivy image pull; DB from the cache |
| build | 1–2 | base image pull; buildx GHA cache |
| image-scan | 1 | artifact download; DB from the cache |
| sbom | 1 | syft image pull |
| dast | 2–3 | ZAP image pull (large), baseline spider |
| sign-and-attest | 0 (skipped) | skipped unless `publish: true` on main |
| gate | 1 | billed minimum |
| **Total** | **~11–14 billed minutes** | wall-clock ~4–6 min, since jobs run in parallel |

Path filters keep the pipeline off PRs that do not touch this project, and
`concurrency: cancel-in-progress` stops superseded runs on the same ref.

## Caching the Trivy DB

Without a cache, every Trivy job downloads the vulnerability DB from
`ghcr.io/aquasecurity/trivy-db`. That is tens of MB per job. The first local
run here took about 4.5 minutes on a slow link, most of it the DB download.
Concurrent CI jobs can also hit GHCR rate limits (`TOOMANYREQUESTS`).

What the workflow does:

```yaml
- id: day
  run: echo "day=$(date -u +%Y-%m-%d)" >> "$GITHUB_OUTPUT"
- uses: actions/cache@<sha> # v6.1.0
  with:
    path: .trivy-cache
    key: trivy-db-${{ steps.day.outputs.day }}
    restore-keys: trivy-db-
```

- The key rotates daily, so the DB is at most a day old. `restore-keys`
  reuses yesterday's DB as a starting point, and Trivy refreshes it if it is
  stale.
- The SARIF pass downloads or refreshes the DB once. The gate pass then runs
  with `--skip-db-update` against the same cache, so a job never downloads
  twice.
- `sca` and `image-scan` share the key. Whichever finishes first saves the
  entry, and the other reuses it the next day.
- Alternative for heavy use: a scheduled workflow downloads the DB once a day
  (`trivy image --download-db-only`) into the cache, and scan jobs always run
  with `--skip-db-update`. If GHCR throttles, point `--db-repository` at the
  mirror on `public.ecr.aws/aquasecurity/trivy-db`.

## Other levers

- **The buildx GHA cache** (`cache-from/to: type=gha`) makes rebuilds of
  unchanged layers almost free. It counts against the repository's Actions
  cache quota.
- **The DAST image is the largest pull.** Run DAST only on `main` or nightly
  if PR latency matters more than per-PR DAST coverage.
- **Self-hosted SonarQube** has its own infrastructure cost. SonarCloud is
  free for public projects. That is part of why Semgrep is the default
  (ADR 0002).
- **Artifacts:** the image tar is about 43 MB (measured locally) and is kept
  for 1 day; the SBOMs are about 3 MB. Storage cost is negligible at that
  retention.
