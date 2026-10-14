# Operations

## 1. Triage a blocking finding

1. Open the failed run's **gate** summary. It names the job that blocked.
2. Open the finding in **Security → Code scanning**, filtered by category
   (`gitleaks`, `semgrep`, `trivy-fs`, `trivy-image`). Or read the failing
   step's log, which prints the table.
3. Decide which case applies:

| Situation | Action |
|---|---|
| Fix available (Trivy shows a *Fixed Version*) | Bump the package or base image. For OS packages, move the pinned base digest forward. This project hit exactly that case: the bookworm base had 37 fixable CRITICAL/HIGH findings, so it moved to trixie. |
| The finding is in a tool the runtime never uses | Remove the tool from the image. In this project the only fixable HIGH findings sat in pip's vendored packages, so the Dockerfile uninstalls pip. |
| Semgrep true positive | Fix the code. Never add `# nosemgrep` without a reason in the same comment and a review. |
| Semgrep false positive | Add `# nosemgrep: <rule-id> -- <reason>` on the line and get a reviewer to approve it. |
| No fix exists and the risk is accepted | Use the exception process in section 2. |
| Secret found | Use the rotation runbook in section 3. Do **not** just delete the line. |

4. Re-run only the failed job after the fix (**Re-run failed jobs**). The gate
   re-evaluates on its own.

## 2. Exception process (with expiry)

Exceptions are code, reviewed like code, and they expire on their own.

**Trivy (`.trivyignore`)**: one line per finding:

```
CVE-YYYY-NNNNN exp:YYYY-MM-DD # reason: why acceptable; owner: team; revisit when ...
```

- `exp:` is Trivy's native field. After that date Trivy stops honouring the
  entry and the gate fails again. Verified locally with Trivy 0.75.0: an entry
  dated 2026-01-01 no longer suppressed its CVE.
- `policy/trivyignore_check.py` runs in the caller's `policy` job. It fails on
  a missing expiry, a missing reason, an expired entry, an expiry more than 180
  days out, or a duplicate. The 180-day ceiling forces a re-review twice a year.
- Prefer `ignore-unfixed: true` over individual entries for "no fix yet" OS
  findings, and keep `.trivyignore` for findings that *have* a fix you are
  deliberately not taking.

**gitleaks (`.gitleaks.toml`)**: an `[[allowlists]]` block with a
`description` that says why. Prefer a `regexTarget = "line"` pattern pinned
to the exact false-positive shape over a whole-path allowlist. The shipped
config allowlists example ECR URIs tagged with a commit SHA under the
documentation account `123456789012`, because gitleaks' `generic-api-key`
rule flagged 4 of them in another project's `*.example` files.

**ZAP (`app/.zap/rules.tsv`)**: `<alert id>\tIGNORE\t(<reason>)`. Only use
it for informational alerts.

Approval (recommended, not shipped in this monorepo): put these three files in
CODEOWNERS so that an exception needs a review from the security owner.

## 3. Rotate a leaked secret (revoke first, then purge history)

The secret is compromised the moment it is pushed. Clones, forks, CI logs
and caches all hold a copy, so rewriting history alone protects nothing.

1. **Revoke or rotate at the provider immediately.** Do this before any git
   work: deactivate the key, issue a new one, and update the secret store
   (GitHub Actions secrets, Secrets Manager, Vault).
2. **Check for use.** Look in the provider's audit trail (CloudTrail, the
   GitHub audit log, the SaaS access logs) for calls made with the old
   credential since the leaking commit's timestamp.
3. **Remove it from the code.** Replace it with a reference to the secret
   store, and add a regression check if the leak came from a new pattern.
4. **Purge history if the repo is or will be public**, or if policy requires
   it. Run `git filter-repo --replace-text <file>` (or BFG) on a fresh mirror
   clone, force-push every affected branch and tag, then ask GitHub Support to
   drop cached views and PR refs. Every collaborator must re-clone.
5. **Close the loop.** Close the code-scanning alert with "revoked", and
   record the timeline in an incident note: leaked at, revoked at, exposure
   window.

## 4. Enable SonarQube / SonarCloud

Sonar needs a **server**, which can be SonarCloud or self-hosted SonarQube,
plus a **token**. Without both the step is skipped and Semgrep stays the SAST
gate (see ADR 0002).

1. Create the project on the server and note the project key (and the
   organization, for SonarCloud).
2. Create a project analysis token and save it as the repository secret
   `SONAR_TOKEN`.
3. In the caller, set `sonar-enabled: true`, `sonar-project-key`, and either
   `sonar-organization` (SonarCloud) or `sonar-host-url` (self-hosted).
4. The scan runs with `sonar.qualitygate.wait=true`, so a failed quality gate
   fails the `sast` job.

If `sonar-enabled: true` but the token is missing, for example on a fork PR
where secrets are not passed, the job emits a warning and skips Sonar rather
than failing.

## 5. Enable Snyk

Save a Snyk API token as the repository secret `SNYK_TOKEN`. When it is
present the `sca` job also runs `snyk test --severity-threshold=high` on
`requirements.txt`. No input is needed. Trivy stays the baseline, so fork PRs
(which get no secrets) are still covered.

## 6. Verify a signature and an attestation

These apply once `publish: true` has run on `main`. Replace the
placeholders. The image is always addressed **by digest**.

```bash
IMAGE=ghcr.io/example-org/devsecops-demo@sha256:<digest>

# cosign keyless: the certificate identity is the workflow file that signed it.
# A reusable workflow signs as the *called* workflow.
cosign verify "$IMAGE" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/example-org/example-repo/\.github/workflows/devsecops-reusable\.yml@refs/heads/main$'

# CycloneDX SBOM attestation made by cosign attest
cosign verify-attestation "$IMAGE" --type cyclonedx \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/example-org/example-repo/'

# SLSA build provenance from actions/attest-build-provenance
gh attestation verify "oci://$IMAGE" --repo example-org/example-repo \
  --signer-workflow example-org/example-repo/.github/workflows/devsecops-reusable.yml
```

Enforce the same checks at deploy time with an admission controller (Sigstore
policy-controller or Kyverno `verifyImages`), so an unsigned image cannot
run. That part is out of scope here.

## 7. Routine

- **Weekly:** review the open code-scanning alerts and the per-file table from
  the caller's whole-repo workflow lint.
- **Monthly:** let Dependabot (`github-actions` and `docker` ecosystems) bump
  the action SHAs and the base-image digest. Each bump is a PR that runs this
  pipeline.
- **Before an exception expires:** the checker prints days left for each
  entry, so renew it with a fresh reason or fix the finding.
