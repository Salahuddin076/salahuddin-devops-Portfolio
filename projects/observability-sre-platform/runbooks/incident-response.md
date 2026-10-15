# Incident response

How SLO pages become incidents. Reference process for the synthetic services
in this project.

## Severity levels

| Level | Definition | Examples | Response |
|---|---|---|---|
| SEV1 | Revenue-critical journey down or badly degraded for many users | checkout availability page, 14.4x burn | page now, incident commander, status page within 15 min |
| SEV2 | Significant degradation, workaround exists or subset of users | checkout latency page, orders freshness page | page now, incident channel, status page if customer-visible |
| SEV3 | Minor or internal impact, slow budget burn | any ticket-tier alert | ticket, next working day |

A page-tier SLO alert starts at SEV2 at least; the incident commander can
raise or lower it.

## Roles

- **Incident commander (IC):** owns the incident, decides, delegates. Does not
  debug. Usually the first on-call responder until handed over.
- **Operations lead:** hands on keyboard; proposes and applies mitigations.
- **Communications lead:** status page, stakeholder updates, keeps the
  timeline in the incident doc.
- **Scribe** (SEV1): records decisions and timestamps.

One person can hold several roles in a small incident. Hand-overs are said out
loud in the incident channel ("I'm handing IC to ...").

## Flow

1. **Detect**: SLO page (Alertmanager -> pager), or a human report.
2. **Declare**: open `#inc-<date>-<short-name>`, pick a severity, assign IC.
3. **Mitigate first**: roll back, fail over, shed load, disable a feature.
   Root cause can wait.
4. **Communicate** on a fixed cadence: SEV1 every 30 minutes, SEV2 every hour.
5. **Resolve** when the SLI is back within objective and the short-window burn
   is below 1x.
6. **Postmortem** for every SEV1, every SEV2 that spent more than 20% of a
   budget, and any incident someone asks for.

## Communications template

```text
[SEV2][investigating] Checkout errors elevated
Impact: about 5% of checkout attempts fail with an error since 14:05 UTC.
What we're doing: rolled back the 13:58 release at 14:20; error rate falling.
Next update: 15:00 UTC or sooner if things change.
IC: <name>  Channel: #inc-2026-09-03-checkout-errors
```

States: investigating -> identified -> monitoring -> resolved.

## Postmortem template (blameless)

```markdown
# Postmortem: <title>  (SEV<n>, <date>)

## Summary
Two or three sentences: what happened, impact, how it was fixed.

## Impact
- Duration: <start> to <end> UTC
- Users affected / requests failed:
- Error budget spent: <x>% of <service>/<slo> (from the SLO dashboard)

## Timeline (UTC)
- hh:mm  event / decision (who acted, what they saw)

## Contributing factors
What made this possible and what made it worse. Systems and conditions, not
people.

## What went well / what was hard

## Action items
| Action | Type (prevent / detect / mitigate) | Owner | Due |
```

**Blameless** means the postmortem asks how the system let a reasonable
person's action cause harm, and fixes the system. Names appear in the timeline
only to say who did what; nobody is graded. The postmortem is reviewed at the
weekly SLO meeting, and "prevent" actions gate lifting a feature freeze
([error-budget-policy.md](error-budget-policy.md)).
