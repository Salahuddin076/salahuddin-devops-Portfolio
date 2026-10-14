# Cost

**All figures are illustrative**, rounded us-east-1 list prices as of
writing, not quotes, and not measured from a running system. Check the AWS
pricing pages before relying on any number. CodeDeploy itself has no
charge for ECS deployments.

## Steady state (rough monthly shape)

| Item | Driver | Note |
|---|---|---|
| Fargate tasks | vCPU-hours and GB-hours | ARM64 (Graviton) is listed about 20% below x86 for the same size |
| Fargate Spot | same, discounted | AWS advertises up to 70% off Fargate; the discount varies and tasks can be reclaimed with a 2-minute warning |
| ALB | hours plus LCUs | One ALB per environment (three hourly charges), required by the CodeDeploy listener model; see below |
| CloudWatch | alarms, Container Insights metrics, log ingestion and storage | 4 alarms per environment (2 metrics x 2 target groups); p95 is an extended statistic, priced like a standard alarm metric |
| Lambda hooks | invocations and duration | A few invocations per deployment: negligible |
| NAT gateway | hours plus GB processed | Usually the largest surprise; VPC interface endpoints for ECR, Logs and Secrets Manager trade per-GB NAT charges for per-hour endpoint charges |

## Blue/green doubles capacity during a deployment

The replacement task set is launched at the full desired count before any
traffic moves, and the original keeps running until the termination wait
ends. For the length of a deployment you pay for roughly **twice the
tasks**:

| Environment | Desired tasks | Doubled window per release (illustrative) |
|---|---|---|
| dev | 1 | shift 0 min + 5 min wait, plus start-up |
| staging | 2 | 9 min linear + 15 min wait |
| prod | 3 | up to 60 min manual-reroute wait + 5 min canary + 60 min termination wait |

Prod's worst case is about two hours of double capacity per release. With
three 1 vCPU / 2 GB tasks that's a small amount per release; with dozens of
large tasks and several releases a day it is not, and the termination wait
is the main lever. The trade is deliberate: those minutes are the window in
which rollback is a listener change instead of a redeploy.

## Spot savings caveats

- **Both colours may be on Spot.** The replacement task set inherits the
  service's capacity provider strategy. In dev (Spot only) a reclaim during
  a deployment can delay or fail it; that's acceptable for dev.
- **The on-demand base is not discounted.** Prod's base of 2 on-demand tasks
  means only the tasks above two are split 1:1 with Spot; at the minimum of
  3 tasks, the third task lands on either provider.
- **Doubled capacity is doubled Spot exposure.** During a deployment the
  base applies to the service, not per task set; how ECS places the
  replacement set's base is worth observing in a sandbox before counting on
  it.
- Savings estimates that assume continuous Spot availability overstate
  them. Count interruptions as extra start-up time and failed deployments.

## ALBs: one per environment

CodeDeploy shifts traffic by rewriting listener default actions, so each
environment has its own ALB ([ADR 0004](decisions/0004-alb-per-environment.md)).
That's a deliberate cost trade-off against a shared ALB.

**Approximate, illustrative figures** (us-east-1 list prices as of writing;
check the ALB pricing page): an ALB's fixed charge is on the order of
USD 0.0225 per hour, about USD 16-17 per month, before LCUs.

| Layout | Fixed ALB charge per month (approx.) |
|---|---|
| One shared ALB (rejected draft) | ~USD 16-17 |
| One ALB per environment (this design) | ~USD 49-50 |
| Difference | ~USD 33 per month, about USD 400 per year |

LCUs scale with traffic, not with the number of ALBs, so splitting them
mostly adds the fixed charge. Idle dev and staging ALBs still bill their
hourly charge, which you could cut by deleting them outside working hours
(at the cost of DNS changes), or by moving to ECS-native blue/green with a
shared ALB.

What the extra money buys: the documented CodeDeploy listener shape, a
separate failure domain per environment, and dev load tests that can't
consume prod's LCUs or touch prod's security group.

## ALB LCUs

An LCU is the highest of four dimensions per hour: new connections, active
connections, processed bytes, and rule evaluations. Notes for this design:

- **Rule evaluations**: none; every listener has only its default action.
- **Test listeners** see almost no traffic: hook samples and manual testing.
- **During a canary** no extra LCUs: the same requests are split across two
  target groups by the weighted default action.
- Each environment's LCUs are billed on its own ALB, so a dev load test
  shows up on dev's bill only.
