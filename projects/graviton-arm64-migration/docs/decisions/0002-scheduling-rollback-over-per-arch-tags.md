# 0002: Scheduling-based rollback over separate per-architecture image tags

## Status

Accepted.

## Context

There are two ways to run a service on two architectures during a migration:

1. **One tag, multi-arch manifest list** (`docker buildx build --platform
   linux/amd64,linux/arm64 --push`). Kubernetes scheduling (`nodeSelector` /
   `affinity` on `kubernetes.io/arch`) decides which platform's layer a node
   actually pulls. The Deployment spec names one image tag regardless of
   which pool it targets.
2. **Two tags, one per architecture** (`service:1.4.0-amd64`,
   `service:1.4.0-arm64`), with the Deployment's `image:` field itself
   switched between them to move a workload.

## Decision

Use one multi-arch tag per release (option 1). `helm/multiarch-app`'s
`architecture` value only ever changes `nodeSelector`/`affinity`; it never
changes `.Values.image.tag`.

## Consequences

- **Rollback is a scheduling change, not an image change.** Flipping
  `architecture` (or disabling the canary) back is a normal rolling update
  of pod spec metadata. There's no "did we also rebuild/re-push the arm64
  tag" question, because there's only one tag and it was already built for
  both platforms together.
- **The two platforms can never silently diverge in content.** A single
  `buildx build --push` either produces both platform manifests from the
  same build context and the same tag, or it fails outright. Two independent
  per-arch tags can be pushed at different times from different commits,
  which is exactly the drift `scripts/compatibility_check.py` (GC008, the
  runtime-version-mismatch rule) exists to catch, and the single-tag
  approach makes structurally harder to introduce in the first place.
- **The trade-off:** a single multi-arch push is one atomic operation,
  touching both platforms whether or not both actually changed. A one-line
  fix that's relevant to only one architecture still rebuilds and re-pushes
  both. This is an acceptable cost for a size of change this project
  targets (a staged migration, not a hotfix pipeline optimized for minimal
  rebuild scope).
- Per-arch tags remain useful for debugging a single platform directly
  (`docker buildx imagetools inspect <tag> --raw` shows both platform
  digests under one tag without needing separate tags at all), so nothing is
  actually lost by not maintaining them as first-class release artifacts.
