# ADR 0002: Validate on a restricted test listener before traffic shifts

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** ecs-fargate-blue-green (portfolio implementation)

## Context

CodeDeploy can route an optional test listener to the replacement task set
before production traffic moves. Without one, the first requests the new
version serves are real users' (a canary slice still means real users).
With one, two questions follow: who may reach it, and what must pass there
before traffic moves.

## Decision

- **One HTTPS test listener (8443) on each environment's own ALB**
  ([ADR 0004](0004-alb-per-environment.md)), with a single default forward
  action that CodeDeploy points at the replacement target group
  (`ignore_changes = [default_action]`). Same certificate and same ALB as
  production, so the test covers TLS and the real ALB path too. The test
  URL is the environment's host name on port 8443, for example
  `https://api.example.com:8443`.
- **Ingress restricted by security group** to that environment's
  `test_listener_cidrs`: the team's range plus the NAT gateway EIPs the hook
  Lambdas egress through. Terraform validation and the policy lint (BG005)
  reject `0.0.0.0/0` and `::/0`.
- **`BeforeAllowTraffic` runs smoke tests against the test listener:**
  `/healthz` returns 200; `/version` returns the image tag of the task
  definition being deployed (read from the deployment's AppSpec, not passed
  in); N further requests are all 200 and their nearest-rank p95 is within
  the environment's budget (800/500/300 ms).
- **`AfterAllowTraffic` repeats the checks on the production URL** once 100%
  is on green, proving the production route serves the new version.
- **Both report exactly once.** Status starts as Failed, flips only on a
  passing result, and is sent from `finally`. The checks stop before the
  Lambda timeout so the report is always sent; otherwise CodeDeploy would
  wait up to an hour for the hook timeout.

## Consequences

Good:

- A broken release (wrong image, failing health, slow) fails before any
  user traffic, and production never moved.
- The version check catches a deployment that started the wrong image, for
  example a task definition rendered from stale values.
- A dev tester can't reach prod's unreleased version: separate ALBs,
  separate security groups, separate CIDR lists.

Accepted costs:

- **The hooks run in the VPC and egress through NAT**, so the NAT EIPs must
  be maintained in the CIDR list. Running them outside the VPC would mean
  opening the test listener to Lambda's whole address range.
- **p95 over 10-30 samples is a coarse signal.** With nearest-rank, one slow
  request in ten fails the check. That's deliberately strict for a gate
  before traffic; real latency regressions under load are the alarms' job.
- **One extra listener per ALB** and one security group rule per test
  CIDR.

## Alternatives considered

- **No test listener, canary only.** Real users find the problem; with
  alarms it's bounded, but it's still users.
- **Test listener open to the internet with an auth header.** Simpler
  networking, but the unreleased version becomes reachable by anyone who
  finds the port, and the header becomes a secret to rotate.
- **`AfterAllowTestTraffic` instead of `BeforeAllowTraffic`.** Equivalent
  timing for checks on the test listener; the task asked for
  `BeforeAllowTraffic`, which also runs after any manual reroute wait, so
  the checks happen right before traffic moves.
