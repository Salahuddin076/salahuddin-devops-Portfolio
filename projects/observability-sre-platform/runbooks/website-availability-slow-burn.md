# Runbook: public-website availability, slow burn (ticket)

**Alerts:** `PublicWebsiteAvailabilityBurnTicket1d` (3x over 1d and 2h),
`PublicWebsiteAvailabilityBurnTicket3d` (1x over 3d and 6h). **Severity:** ticket.
**SLO:** 99.5% of blackbox probes succeed over 30 days.

## What it means

Probes fail intermittently: more than 1.5% (3x) or 0.5% (1x) over a day or
more. This tier also catches a sustained 6x burn, since the site has no 6x page.

## Within one working day

1. Which probes fail? `probe_success == 0` by instance and prober location.
2. Failure pattern: timeouts (`probe_duration_seconds` near the module
   timeout) point at origin capacity; HTTP 5xx at the origin or CDN; TLS errors
   at certificates.
3. Open a ticket for `team=web` with the failing intervals.

## Close-out

A flaky prober is not a reason to lower the SLO: fix or replace the prober,
and document the exclusion in the SLO review notes.
