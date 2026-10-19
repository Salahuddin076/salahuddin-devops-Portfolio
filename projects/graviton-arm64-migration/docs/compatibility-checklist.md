# Compatibility checklist

A per-service checklist before a service is allowed past `rollout.stage:
design` in `docs/compatibility-manifest.yaml`. `scripts/compatibility_check.py`
enforces the parts that are machine-checkable (rules GC001-GC008, below);
the rest needs a human to actually run the service and look.

## 1. Native build agents vs QEMU emulation

- Prefer a native arm64 build agent (a Graviton CI runner, or an arm64
  Jenkins agent — see `ci/Jenkinsfile`) over `docker buildx` with QEMU
  user-mode emulation.
- QEMU is fine for a pure-script service with no compiled dependencies. For
  anything with native modules (a C extension, a Go/Rust binary, a package
  with prebuilt wheels) it is both slow (minutes become tens of minutes) and
  unreliable in a specific way: a native-module build failure under
  emulation can look like success (the build completes) while the resulting
  binary is subtly wrong, miscompiled for the emulated instruction set, or
  silently falls back to a pure-Python/interpreted path that isn't actually
  exercised the same way on real hardware.
- `compatibility_check.py` rule **GC006** (warning) flags any `qemu`
  `build_method`; **GC007** (error) escalates it to a hard failure when the
  service also lists `native_modules` — see
  [decisions/0001-native-arm64-build-agents.md](decisions/0001-native-arm64-build-agents.md).

## 2. Base image per platform

- Record a base image **per platform**, not one image name assumed to work
  on both. Most official images (`python`, `node`, `golang`, distro bases)
  do publish both `linux/amd64` and `linux/arm64` variants under the same
  tag, but a smaller or vendor-specific base image may not, and the two
  variants can trail each other by a patch release.
- Pin **by digest, per platform** (`image@sha256:<64 hex>`), not by tag. A
  manifest-list digest, pulled by platform, gives you the single digest for
  *that platform's* layer — the thing that can actually drift out from under
  you between a staging run and a prod rollout.
- `compatibility_check.py` rule **GC002** (error) rejects anything not
  matching `@sha256:<64 hex>`.

## 3. Native modules and runtime version per arch

- List every native module/dependency a service ships (`native_modules` in
  the manifest): anything with a compiled extension, a vendored binary, or a
  platform-specific wheel/package.
- Record the exact runtime version per platform
  (`runtime_version`). They should normally match; if they don't, the
  manifest requires `runtime_version_note` explaining why (rule **GC008**,
  warning) — for example "arm64 image intentionally one patch ahead to pick
  up an arm64-specific bugfix."
- Sidecars and agents (APM agents, service mesh sidecars, log shippers) need
  the same per-platform check: some vendors ship amd64-only agents, which
  would otherwise show up as a missing capability only once a pod lands on
  Graviton.

## 4. Image scanning per architecture

- Scan **both** platform images, not just the tag. The two platforms don't
  share layers below the application layer, so a CVE in an arch-specific
  system package (for example a `libc` or `openssl` build difference) can
  exist on one platform and not the other.
- `terraform/modules/ecr-multiarch` scans on push by default
  (`scan_on_push = true`) and supports continuous/enhanced scanning
  (`enhanced_scanning = true`) for the period a migration is actively
  pushing both platforms.
- `compatibility_check.py` rule **GC003** (error) requires a recorded
  `image_scan.status` per platform; **GC004** (error) blocks promoting
  `rollout.stage` to `canary`/`partial`/`complete` unless both platforms show
  `status: pass`; **GC005** (error) catches a `pass` status that still lists
  critical/high findings (a stale or copy-pasted record).

## 5. Sign-off and promotion

`rollout.stage` moves: `design` -> `native-agents` (build pipeline covers
both platforms) -> `canary` (small Graviton pool behind the shared Service,
see [architecture.md](architecture.md)) -> `partial` (Graviton pool widened,
x86 pool kept at capacity) -> `complete` (x86 pool scaled down, kept, not
deleted, until the rollback window closes). Moving a service to `canary` or
beyond without a passing scan on both platforms is rejected by the linter
(GC004); moving it back a stage (or just removing the canary's node
affinity) is always available and is the actual rollback path — see
[operations.md](operations.md).
