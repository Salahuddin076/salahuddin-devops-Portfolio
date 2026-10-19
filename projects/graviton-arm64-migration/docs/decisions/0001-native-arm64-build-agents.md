# 0001: Native ARM64 build agents over QEMU emulation

## Status

Accepted.

## Context

`docker buildx` can produce an arm64 image two ways: cross-compile/build on
an amd64 host using QEMU user-mode emulation for the arm64 steps, or run the
build on a real arm64 host (an EKS/EC2 Graviton build agent, or a
Graviton-backed CI runner). Emulation needs no extra infrastructure — one
build agent handles both platforms. Native agents need a second agent pool
and roughly double the CI fleet to manage.

## Decision

Use native arm64 build agents for any service that lists `native_modules`
in `docs/compatibility-manifest.yaml` (`scripts/compatibility_check.py` rule
GC007 makes this a hard failure, not just a recommendation). QEMU emulation
is allowed for services with no compiled dependencies, where it's mostly
slower, not wrong (GC006 flags it anyway, as a warning, for visibility).

`ci/Jenkinsfile` shows both: it runs the amd64 leg on a standard agent and
the arm64 leg on an agent labeled for Graviton hardware, then merges both
platform pushes into one manifest list with `docker buildx imagetools
create` (an alternative to a single multi-platform `buildx build --push`
when the two legs run on genuinely separate agents/hosts).

## Consequences

- Native agents cost more to run and maintain (a second instance family,
  possibly a second CI agent image) than one QEMU-capable amd64 fleet.
- In exchange, a native-module build failure surfaces as a build failure,
  not as a binary that builds under emulation and then behaves differently
  (or crashes) only once it's actually running on real arm64 hardware in a
  canary pod — the failure mode this decision is trying to move earlier.
- Build time for native-module services on arm64 agents is close to the
  amd64 build time; under QEMU it's commonly 5-10x slower for anything that
  compiles.
- A service with no native modules keeps the simpler single-agent QEMU path
  until something about it changes (a new dependency added later re-triggers
  the GC007 check against the updated manifest).
