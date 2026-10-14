# ADR 0001: ECS rolling deploys with the circuit breaker, not CodeDeploy blue/green

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-codepipeline-container-delivery (portfolio implementation)

## Context

The pipeline has to replace a running ECS Fargate service with a new image
twice per release (staging, then prod) and recover by itself when the new
version can't start. CodePipeline offers two deploy integrations for ECS:

1. **The ECS standard deploy action** (`provider = "ECS"`). It reads
   `imagedefinitions.json`, registers a new task definition revision and
   calls `UpdateService`. ECS then performs a rolling update governed by
   `minimumHealthyPercent` / `maximumPercent`. The deployment circuit
   breaker can roll back automatically.
2. **CodeDeploy blue/green** (`provider = "CodeDeployToECS"`). It needs an
   Application Load Balancer with two target groups, a production listener
   (and optionally a test listener), an `appspec.yaml` and a
   `taskdef.json` artifact, a CodeDeploy application and deployment group,
   and the ECS service on the `CODE_DEPLOY` deployment controller. Traffic
   shifts all at once, linearly or canary, with alarm-based rollback and a
   wait period during which the old tasks stay up.

This service has no load balancer. It is a small internal HTTP service, and
the point of this project is the delivery pipeline: source, test, build,
scan, promote, approve.

## Decision

Use the **ECS standard deploy action** with a rolling update
(`minimumHealthyPercent = 100`, `maximumPercent = 200`) and the
**deployment circuit breaker with `rollback = true`**. Add **CodePipeline V2
stage rollback** (`on_failure { result = "ROLLBACK" }`) on both deploy
stages, so a failed deploy also returns the pipeline to the last good
artifact.

Health is decided by the container health check (`/healthz` through
`healthcheck.py`), defined in the task definition, because ECS ignores the
image's `HEALTHCHECK`. The app also refuses to start when its secret is
missing or malformed, which turns configuration errors into failed task
starts the breaker can see.

## Consequences

Good:

- **Few moving parts.** No ALB, no target-group pair, no appspec, no
  CodeDeploy application. The deploy artifact is a single file the build
  generates and validates (`make_imagedefinitions.py`).
- **Automatic recovery from the common failure.** A release that crashes on
  start, can't pull its image, can't resolve its secret or fails its health
  check is rolled back by ECS without a person.
- **Same mechanism in both environments.** What staging exercises is
  exactly what prod uses.

Accepted costs:

- **No traffic control.** During a rolling update, old and new tasks serve
  side by side, briefly. There is no canary percentage, test listener or
  bake time with instant switch-back.
- **The breaker only sees "doesn't start or isn't healthy".** A release that
  is healthy but wrong goes fully live. Recovery is a manual redeploy of a
  previous SHA ([operations](../operations.md#rolling-back)). Adding
  CloudWatch alarms to the service's `alarms` block would extend automatic
  rollback to error rates, and that's the natural next step.
- **The breaker is not instant.** Its failure threshold depends on the
  desired count, so detection takes several failed task launches.

## Alternatives considered

- **CodeDeploy blue/green.** The right choice when a service sits behind an
  ALB and needs zero-mixed-version cutover, canary traffic, or a test
  listener for pre-traffic checks. **A sibling portfolio project covers
  blue/green with CodeDeploy**, including the listener and target-group
  wiring and the lifecycle hooks. Combining both here would hide the
  pipeline under load balancer plumbing.
- **ECS-native blue/green and canary** (`deployment_configuration.strategy`,
  newer in the ECS API and supported by the aws provider 6.x schema). It
  removes the CodeDeploy dependency but still needs a load balancer or
  Service Connect to shift traffic. It's worth evaluating for the
  blue/green sibling. It isn't needed for a service without inbound traffic
  management.
- **Rolling without the circuit breaker.** ECS would keep replacing failing
  tasks until the action's `DeploymentTimeout`, then the action fails with
  the service in a broken state. Never acceptable.
