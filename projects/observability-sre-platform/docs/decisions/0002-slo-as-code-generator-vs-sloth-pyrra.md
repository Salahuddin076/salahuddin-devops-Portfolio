# ADR 0002: A stdlib SLO generator here, instead of Sloth or Pyrra

**Status:** accepted for this reference implementation

## Context

SLOs should be code: reviewed in pull requests, generating the rules and
dashboards so nobody hand-edits PromQL with magic numbers. Mature open-source
tools already do this:

- **Sloth**: SLO spec (YAML or a Kubernetes CRD) -> Prometheus recording and
  multi-window multi-burn-rate alert rules; plugins for common SLIs; Grafana
  dashboards available.
- **Pyrra**: SLO CRDs or files -> rules, plus its own UI showing budgets and
  burn rates, with a Kubernetes operator.
- Vendor SLO features (Grafana SLO, Datadog, Nobl9) for teams on those platforms.

## Decision

In this repository the generator is about 700 lines of stdlib Python
(`generator/slogen.py`). The purpose is to **show the math**: error budget,
burn thresholds, budget consumed per window, the `or vector(0)` outage case,
the error-budget replay over historical counts, with every number tested by
hand and the output tested by promtool.

**In many organisations, Sloth or Pyrra would be the right choice**, and I
would usually start there: they are maintained, documented, and familiar to
the next engineer. The output of this generator is deliberately close to
Sloth's (`slo:sli_error:ratio_rate<window>` naming, the same tiers), so moving
to Sloth later changes the source format, not the dashboards or the alerts'
meaning.

## When a custom generator is justified in real life

- The SLO source must come from somewhere else (a service catalogue).
- Outputs Sloth / Pyrra don't produce (here: the hourly error-budget replay,
  per-alert budget math in annotations, runbook links by convention).
- A non-Prometheus backend.

## Consequences

- No dependency to install or pin; CI runs it with plain Python 3.12.
- We own the maintenance and correctness. That's why the generated output is
  checked into git with a "regenerate gives no diff" CI step, unit tests cover
  the math, and promtool tests the rules end to end.
- No SLO UI: Grafana dashboards only.
