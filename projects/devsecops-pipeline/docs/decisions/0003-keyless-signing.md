# ADR 0003: Keyless signing with cosign, and GitHub build provenance

- **Status:** accepted
- **Date:** 2026-10-14

## Context

Consumers of the image need to verify two things: that this pipeline
produced it, and how. Long-lived signing keys must be stored, rotated and
protected, and a leaked key signs anything, indefinitely.

## Decision

- **cosign keyless signing.** The `sign-and-attest` job requests a GitHub
  OIDC token (`id-token: write`, on that job only). Sigstore Fulcio exchanges
  it for a short-lived certificate whose identity is the workflow
  (`.../.github/workflows/devsecops-reusable.yml@refs/heads/main`). The
  signature is recorded in the Rekor transparency log. There is no key to
  store or rotate.
- The image is signed **by registry digest** after pushing the exact tar that
  was scanned. The CycloneDX SBOM is attached as a cosign attestation.
- **SLSA build provenance** comes from `actions/attest-build-provenance`
  (`attestations: write`), and is pushed to the registry next to the image.
  It is verifiable with `gh attestation verify`.
- **Off by default.** The job runs only when `publish: true` **and** the
  event is a push to `main`. This portfolio repository sets `publish: false`:
  it has no registry it should write to, and it should not mint signing
  identities. Its caller still grants the permission ceiling, because GitHub
  validates nested permissions when the run starts.

## Consequences

- Verification pins the signer's identity (repository, workflow file and ref)
  and the OIDC issuer, not a public key. operations.md §6 has the commands.
- Signing depends on the public Sigstore infrastructure (Fulcio, Rekor) being
  reachable. Air-gapped environments would need a private Sigstore or
  key-based signing in a KMS.
- Signing proves origin, not safety. Enforcement belongs in an admission
  controller (policy-controller or Kyverno), which is out of scope here.
- The signing path has never run (no registry, no push to main from this
  repository). Treat it as unverified until it runs once in a sandbox
  repository.
