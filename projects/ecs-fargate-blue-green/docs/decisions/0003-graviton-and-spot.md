# ADR 0003: Graviton (ARM64) tasks with a per-environment Spot mix

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** ecs-fargate-blue-green (portfolio implementation)

## Context

The app is pure Python with no native dependencies, so it runs the same on
ARM64 and x86_64. Fargate prices ARM64 below x86 for the same size, and
Fargate Spot discounts further at the cost of interruptions. ARM64 tasks
on Fargate Spot have been supported since September 2024 (platform version
1.4.0 or later). Blue/green complicates Spot because the replacement task
set inherits the service's capacity provider strategy.

## Decision

- **`runtime_platform.cpu_architecture = ARM64`** in every environment, as
  a validated variable (`ARM64` or `X86_64`). The Dockerfile uses a
  multi-arch base, CI builds `linux/arm64` with buildx and QEMU, and the
  hook Lambdas run on arm64 too.
- **Capacity provider strategy per environment:** `FARGATE` with a base and
  weight, plus `FARGATE_SPOT` with a weight (Spot never gets a base).
  - dev: Spot only (`on_demand_weight = 0`, `spot_weight = 1`).
  - staging: on-demand base 1, then 1:1.
  - prod: on-demand base 2, then 1:1.
- **Documented, not hidden:** with blue/green, both task sets may run on
  Spot during a deployment, so a reclaim can hit the old and the new
  version at once. The on-demand base is the floor that a reclaim can't
  take.

## Consequences

Good:

- Lower cost per task in every environment (illustrative figures in
  [cost](../cost.md)).
- dev exercises Spot behaviour, including interruptions during deployments,
  where it's cheap to learn.

Accepted costs:

- **The image must be built for ARM64.** An x86 image on an ARM64 task fails
  with `exec format error`. CI builds arm64; multi-arch manifests would
  allow switching architecture by variable alone.
- **Spot interruptions during a deployment** can delay it or fail it into a
  rollback, mostly in dev.
- **How the base applies during a deployment** (to the service, while two
  task sets exist) is not verified here; observe it in a sandbox before
  relying on prod's floor of 2.
- **Emulated CI builds are slower** (QEMU) than native arm64 runners.

## Alternatives considered

- **x86_64 everywhere.** Simplest for teams with native dependencies; costs
  more with no benefit for this app.
- **Spot in prod without a base.** Cheapest, but a capacity reclaim could
  take every task, in both colours, during a deployment.
- **On-demand only everywhere.** Predictable; gives up the Spot discount
  where interruptions don't matter (dev).
