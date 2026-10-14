# ADR 0004: One ALB per environment, listeners with a single default action

- **Status:** Accepted (supersedes the shared-ALB draft)
- **Date:** 2026-10-14
- **Context:** ecs-fargate-blue-green (portfolio implementation)

## Context

CodeDeploy blue/green for ECS shifts traffic by changing **listeners**. The
deployment group names a production listener and an optional test
listener. During a deployment CodeDeploy points the test listener's
default action at the replacement target group, then steps the production
listener's default action from the original target group to the
replacement one (a weighted forward for canary and linear configs).

The first draft of this project put dev, staging and prod behind **one
shared ALB**. Each environment's production route was a host-header rule
(`dev.api.example.com`, `staging.api.example.com`, `api.example.com`) on a
shared 443 listener whose default action returned 404. The design only
works if CodeDeploy rewrites a **non-default rule** that forwards to the
original target group, and leaves the other environments' rules on the
same listener alone. What the sources say:

- The CodeDeploy guide
  [Set up a load balancer, target groups, and listeners for CodeDeploy Amazon ECS deployments](https://docs.aws.amazon.com/codedeploy/latest/userguide/deployment-groups-create-load-balancer-for-ecs.html)
  describes one required production listener and an optional test
  listener, each created with a **default action** forwarding to a target
  group. It doesn't mention listener rules.
- The AWS Containers blog post
  [Migrating from AWS CodeDeploy to Amazon ECS for blue/green deployments](https://aws.amazon.com/blogs/containers/migrating-from-aws-codedeploy-to-amazon-ecs-for-blue-green-deployments)
  says CodeDeploy "needs separate listeners for different services, and
  for production and test endpoints", each "configured with a single
  (default) rule". It contrasts this with ECS-native blue/green, which
  "operates at the listener rule level".

Community reports suggest CodeDeploy can handle rules, but nothing here
could prove it without deploying, and a wrong guess is an outage. If the
original target group is left behind on a rule, production keeps routing to
it until it is terminated.

## Decision

- **One ALB per environment**, created by `modules/ecs-service-bluegreen`:
  `bluegreen-dev-alb`, `bluegreen-staging-alb`, `bluegreen-prod-alb`.
- On each ALB, the **production listener (443)** and the **test listener
  (8443)** have a **single default forward action** to the blue/green pair,
  with `lifecycle { ignore_changes = [default_action] }`, because CodeDeploy
  owns it after creation. There are no listener rules; a static test fails
  if an `aws_lb_listener_rule` appears.
- **DNS per environment**: `dev.api.example.com`, `staging.api.example.com`
  and `api.example.com` each alias their own ALB (`alb_dns_name` output).
  The host names are unchanged; only what they resolve to differs.
- **ECR and the ECS cluster stay shared** in `modules/shared-platform`: one
  image promoted by tag, one cluster with FARGATE and FARGATE_SPOT.

## Consequences

Good:

- **Matches the documented CodeDeploy shape**, so nothing in the traffic
  path depends on undocumented behaviour.
- **Separate blast radius.** A listener mistake, an LCU spike from a dev
  load test, or a security group change affects one environment only.
- **Simpler security groups.** Each ALB's security group holds only its
  environment's test CIDRs, on one port (8443).

Accepted costs:

- **Three ALB hourly charges instead of one**, plus three sets of LCUs.
  Illustrative and approximate: an ALB's fixed charge is on the order of
  USD 16-17 a month in us-east-1 before LCUs, so the change adds roughly
  USD 33 a month at idle (see [cost](../cost.md)). Check current pricing.
- **Three DNS alias records** pointing at different ALBs, and three
  certificates attached (one ACM certificate covering `api.example.com` and
  `*.api.example.com` can be reused).
- **More resources per environment** in Terraform.

## Alternatives considered

- **Shared ALB with host-header rules (the draft).** Rejected as
  unverified against the documentation above, not as proven broken.
- **Shared ALB with a dedicated production listener per environment**
  (prod on 443, staging and dev on other ports). Documented shape and one
  ALB, but non-standard public ports for dev and staging, and every
  environment shares one security group and one failure domain.
- **ECS-native blue/green** (`deployment_configuration.strategy` on the
  service). It works at the listener-rule level, so it is the right
  choice **if a shared ALB is a hard requirement**: host rules on one 443
  listener, each rule forwarding to a weighted pair. It replaces CodeDeploy,
  the appspec and the `CodeDeployDefault.*` configs with ECS's own
  deployment settings and lifecycle hooks. The task required CodeDeploy, so
  it stays the documented fallback.
