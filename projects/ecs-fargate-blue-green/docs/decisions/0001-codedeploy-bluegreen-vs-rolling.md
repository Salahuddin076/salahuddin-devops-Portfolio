# ADR 0001: CodeDeploy blue/green instead of ECS rolling updates

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** ecs-fargate-blue-green (portfolio implementation)

## Context

The sibling project
[aws-codepipeline-container-delivery](../../../aws-codepipeline-container-delivery/)
deploys with ECS rolling updates and the deployment circuit breaker, and
its [ADR 0001](../../../aws-codepipeline-container-delivery/docs/decisions/0001-ecs-rolling-with-circuit-breaker.md)
records what that leaves out: no route to the new version before users
reach it, no traffic percentages, a healthy-but-wrong release going fully
live, and rollback by redeploying. It names a blue/green sibling as the
place to cover those. This is that project.

This service sits behind an ALB, has three environments with different
risk tolerance, and needs a validation step before production traffic.

## Decision

Use **AWS CodeDeploy blue/green for ECS**: the service on the `CODE_DEPLOY`
deployment controller, two target groups per environment, a production
route and a dedicated test listener, a deployment group with:

- a per-environment `deployment_config_name` (dev `AllAtOnce`, staging
  `Linear10PercentEvery1Minutes`, prod `Canary10Percent5Minutes`);
- auto-rollback on `DEPLOYMENT_FAILURE` and `DEPLOYMENT_STOP_ON_ALARM`, with
  5xx and p95 latency alarms on the target groups;
- a termination wait on every environment (5/15/60 minutes) so the old task
  set stays up as the rollback target;
- in prod, a manual reroute: CodeDeploy waits for `continue-deployment`
  before production traffic moves;
- `BeforeAllowTraffic` and `AfterAllowTraffic` Lambda hooks.

Terraform creates the service and routes; CodeDeploy owns the task
definition and which target group is live. `ignore_changes` on the service
(`task_definition`, `load_balancer`) and on the routes (`action`,
`default_action`) records that split.

## Consequences

Good:

- **Pre-traffic testing.** The replacement task set answers on the test
  listener before any user does, and a failed hook stops the deployment
  with production untouched.
- **Bounded blast radius.** A canary alarm at minute 3 costs 10% of traffic
  for a few minutes (see `traffic_shift_sim.py`).
- **Fast rollback.** While blue exists, rollback is a listener change.
- **Alarm-driven rollback** covers what the circuit breaker can't: a
  release that starts and passes health checks but errors or slows down.

Accepted costs:

- **More moving parts.** Two target groups, a test listener, an appspec,
  hook Lambdas and a CodeDeploy application per environment.
- **Double capacity during deployments** (see [cost](../cost.md)).
- **Terraform no longer deploys.** Changing the task definition in Terraform
  registers a revision but moves nothing; releases go through
  `create-deployment` ([operations](../operations.md)). People new to the
  setup find this confusing, so the runbook calls it out.
- **Limited service updates.** Services on the `CODE_DEPLOY` controller
  accept only some changes through `UpdateService`; network and capacity
  changes go through the appspec or a service replacement.
- **One ALB per environment.** CodeDeploy's documented shape is a
  production and a test listener per service, each with a single default
  action, so environments can't share one listener through host rules
  ([ADR 0004](0004-alb-per-environment.md)).

## Alternatives considered

- **ECS rolling with the circuit breaker** (the sibling). Simpler, and the
  right default for internal services without an ALB. Not enough here:
  no test route, no traffic control, no alarm rollback without extra wiring.
- **ECS-native blue/green** (`deployment_configuration.strategy`). Removes
  CodeDeploy, works on listener rules, and has its own lifecycle hooks.
  Newer, and its traffic-shifting options have changed since launch; the
  task asked for CodeDeploy, which remains the widely deployed pattern. It's
  the documented alternative if one shared ALB becomes a requirement.
- **Two services behind weighted target groups, switched by hand or by a
  script.** Full control, but rollback, alarms and hook orchestration
  become our code instead of a managed service's.
