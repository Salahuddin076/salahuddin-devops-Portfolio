# Runbook: public-website availability, fast burn (page)

**Alert:** `PublicWebsiteAvailabilityBurnPage1h` (14.4x over 1h and 5m).
**Severity:** page. **SLO:** 99.5% of blackbox probes against
https://www.example.com succeed over 30 days (budget 0.5%). 14.4x means more
than 7.2% of probes fail. There is no 6x page for this site on purpose: it is
not revenue-critical, so a sustained 6x burn opens a ticket through the 1d tier.

## First five minutes

1. Is it the site or the prober? Check probes from a second location or run
   `curl -sS -o /dev/null -w '%{http_code} %{time_total}\n' https://www.example.com`.
   If only one prober fails, it's the prober's network: silence with a reason.
2. Probe details: `probe_http_status_code`, `probe_duration_seconds`,
   `probe_ssl_earliest_cert_expiry` (an expired certificate fails every probe).
3. CDN and DNS status; recent deploys of the site.

## Common causes

- Certificate expired or wrong chain: renew; add an expiry alert if missing.
- CDN origin errors after a deploy: roll back the site.
- DNS change: check the record and TTL.

## After

Record the budget spent. If certificate expiry caused it, the postmortem
action is an expiry alert 21 days ahead, not a looser SLO.
