# ADR 0001: One reusable workflow, called per project

- **Status:** accepted
- **Date:** 2026-10-14

## Context

The security gates (secrets, SAST, SCA, image scan, SBOM, signing, DAST) are
the same for every containerised service. When each team copies them into its
own workflow, the copies drift: one pins a SHA and another a tag, one blocks
on HIGH and another only on CRITICAL, one scopes `security-events: write` and
another sets `write-all`. Each improvement also has to be made N times.

Options considered:

1. **Copy-paste per project.** Simple, but the copies drift. Rejected.
2. **Composite action.** It can bundle steps, but not jobs. Every scanner
   would then share one job's permissions, so `security-events: write` and
   `id-token: write` would sit next to every scanner. It also cannot fan out
   in parallel. Rejected.
3. **Reusable workflow (`on: workflow_call`).** Separate jobs with separate
   `permissions:` blocks, parallel by default, typed inputs and optional
   secrets, versioned by git ref.

## Decision

Use a reusable workflow at `.github/workflows/devsecops-reusable.yml`. GitHub
only loads reusable workflows from the repository's root `.github/workflows/`,
so it cannot sit under `projects/`. Each project gets a thin caller that sets
inputs (directory, image name, thresholds, feature flags) and maps the
optional secrets explicitly rather than `secrets: inherit`.

## Consequences

- One place to raise the bar, and every caller gets the change on its next run.
  Cross-repository callers should pin the reusable workflow by SHA, the same
  way as any other action (rule WF010 already enforces that).
- The caller must grant the **union** of the permissions the called jobs
  might need, because GitHub checks nested permissions at run start. Each
  called job narrows again, so `id-token: write` only ever reaches
  `sign-and-attest`. That job's `if:` keeps it off pull requests.
- Project-specific checks (this project's unit tests, `.trivyignore` expiry,
  the workflow lint) stay in the caller, so the reusable workflow does not
  depend on any project's scripts.
- `gate` is the single required status check, so branch protection does not
  change when jobs are added.
