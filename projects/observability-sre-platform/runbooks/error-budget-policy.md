# Error-budget policy

Applies to every SLO in `slo/`. Agreed between the service team, product
owner and SRE; reviewed every quarter. Values below are a reference policy for
synthetic services, not figures from a real organisation.

## Definitions

- **Error budget** = 1 - objective over the SLO window (99.9% over 30d ->
  0.1% of requests, about 43 minutes of full outage).
- **Budget remaining** = the dashboard's *Error budget remaining*
  (`slo:period_error_budget_remaining:ratio`).
- **Exhausted** = remaining at or below 0% over the rolling window.

## Budget states and what happens

| Remaining | State | What changes |
|---|---|---|
| > 50% | healthy | Ship as normal. Budget can be spent on planned risk (migrations, experiments). |
| 25% - 50% | caution | Reliability items get priority in planning. Risky changes need a rollback plan reviewed by a second engineer. |
| 0% - 25% | at risk | Only changes with a tested rollback ship. The team reserves at least 25% of the next iteration for reliability work. |
| <= 0% | exhausted | **Feature freeze** for that service (below). |

## Feature freeze

While the budget is exhausted:

- Only these changes ship: fixes for the reliability problem, security
  patches, legal or compliance changes, and changes that reduce risk
  (rollbacks, feature-flag kills).
- The freeze lifts when the rolling budget is back above 0% **and** the
  postmortem action items marked "prevent recurrence" are done or scheduled.
- A freeze longer than two weeks is escalated to the engineering lead.

## Exceptions

- **Dependency outage**: if a documented dependency (cloud provider, payment
  provider) caused more than half of the spend, the review can lift the freeze
  early. The incident still gets a postmortem, and the dependency's reliability
  becomes a review item.
- **Business-critical launch**: the product owner and the engineering lead can
  approve a one-off exception in writing, with a named rollback owner.
- **Bad measurement**: if the SLI was wrong (prober outage, broken
  instrumentation), the review can exclude the interval. Write down the
  interval and the reason; never edit the data.

## Single incidents

One incident that spends more than 20% of a budget gets a postmortem
regardless of the budget state ([incident-response.md](incident-response.md)).

## Review cadence

- **Weekly** (30 minutes, per team): burn-rate trend, budget remaining, open
  slow-burn tickets.
- **Monthly**: SLO attainment per service, freezes and exceptions granted.
- **Quarterly**: are the objectives still right? Change them in `slo/*.json`
  through a pull request with the reasoning (docs/operations.md). Tightening
  or loosening an SLO is a product decision, not a way out of a freeze.
