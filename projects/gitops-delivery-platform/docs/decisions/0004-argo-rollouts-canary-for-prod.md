# ADR 0004: Argo Rollouts canary with metric analysis for prod only

- Status: accepted
- Date: 2026-10-15

## Context

A Deployment's rolling update replaces every pod as soon as the new ones are
Ready. Readiness says the process is up, not that it serves requests
correctly; a bad release reaches all prod traffic in a minute or two.

## Decision

In prod, the chart renders an Argo Rollouts `Rollout` with a canary strategy:
10% weight, a 2-minute pause, an analysis run, 50%, a 5-minute pause, another
analysis, then 100%. The `AnalysisTemplate` queries Prometheus for the
canary pods' success rate (non-5xx / all, the availability SLI from
projects/observability-sre-platform) every minute, five times, and needs at
least 0.99; two failed measurements abort the rollout. `rollout.enabled`
toggles it per environment; dev and staging keep a plain Deployment.

## Why

- **The gate is the SLI the service is held to**, not CPU or readiness.
- **Automatic abort** limits the impact to the canary's share of traffic for a
  few minutes, without a human watching dashboards.
- **dev and staging stay simple and fast**: rollouts there are frequent,
  traffic is synthetic, and a canary would only slow feedback.
- Argo Rollouts integrates with Argo CD's health (a paused rollout is
  Suspended, an aborted one Degraded, which triggers the notification).

## Alternatives

- **Blue/green** (Rollouts or two Deployments): a fast full switch and easy
  rollback, but the whole of traffic moves at once and it needs double
  capacity during the switch.
- **Flagger**: equivalent, pairs naturally with Flux.
- **Plain Deployment plus alerting**: detects the problem only after it
  reaches all users.

## Consequences

- Without a traffic router, weights follow the canary/stable pod ratio: with 4
  replicas, "10%" rounds up to one canary pod next to three stable ones (25%). Adding the NGINX or ALB
  traffic router gives exact weights; it needs a canary and a stable Service.
- The analysis needs traffic. A canary that receives none fails (no data is
  not success), so low-traffic hours need synthetic load or a longer pause.
- The HPA targets the Rollout, and `ignoreDifferences` covers
  `Rollout /spec/replicas` as well as Deployments.
- Engineers need the `kubectl argo rollouts` plugin for abort, promote and
  undo (docs/operations.md).
