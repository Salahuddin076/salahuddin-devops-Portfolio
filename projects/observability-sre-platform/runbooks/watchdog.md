# Runbook: Watchdog (dead man's switch)

**Alert:** `Watchdog`, expression `vector(1)`, severity `none`. It is meant to
fire all the time.

## How it works

Alertmanager routes `Watchdog` to the `deadmans-switch` receiver with
`repeat_interval: 1m`: an external heartbeat service gets a request every
minute. If the requests stop for longer than the heartbeat's grace period
(set it to about 5 minutes), **the heartbeat service pages**, because one of
these is broken:

- Prometheus is down or not evaluating rules;
- the rule files failed to load (a bad generated rule would show in
  `prometheus_rule_group_last_evaluation_timestamp_seconds`);
- Prometheus can't reach Alertmanager (`prometheus_notifications_dropped_total`);
- Alertmanager is down or can't reach the internet.

## When the heartbeat service pages

1. Prometheus up? `/-/ready`; rule evaluation:
   `time() - prometheus_rule_group_last_evaluation_timestamp_seconds > 120`
2. Notifications: `rate(prometheus_notifications_errors_total[5m])`
3. Alertmanager up? `/-/ready`; failed sends:
   `rate(alertmanager_notifications_failed_total{integration="webhook"}[5m])`
4. Until it's fixed, **assume no SLO alert will reach anyone**: put someone on
   the dashboards.

## Never

Silence `Watchdog` in Alertmanager. That stops the heartbeat and triggers the
external page, which is the correct outcome.
