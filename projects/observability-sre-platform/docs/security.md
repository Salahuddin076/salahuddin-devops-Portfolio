# Security

## PII scrubbing (OTel Collector)

Telemetry leaks personal data in predictable places: auth headers, cookies,
user attributes, and query strings. The Collector gateway is the one choke
point every trace and log passes through, so scrubbing happens there (ADR 0003):

- `attributes/scrub-pii` **deletes** `http.request.header.authorization`,
  cookies, `user.email`, `user.phone`, `user.full_name`, and any key matching
  `password|passwd|secret|token|api_key`.
- It **hashes** `enduser.id`, `user.id` and `client.address`, so they still join
  across traces and logs without exposing the raw value.
- `transform/strip-query` removes query strings from `url.full` / `http.url`.
- Order: `memory_limiter` -> scrub -> `batch`, so nothing unscrubbed is
  batched or exported. A test checks the order in every pipeline.

Limits, stated plainly:

- An unsalted hash of a low-entropy value can be reversed by guessing (hash
  every e-mail address you know, compare). That's why e-mails and phone
  numbers are deleted, not hashed. Hashed IDs are pseudonymous, not anonymous.
- Attribute rules don't see free text: a log **body** containing an e-mail
  passes through. Fix it at the source (structured logging), or add a
  `transform` with `replace_pattern` on `log.body`, which costs CPU on every record.
- Metrics labels are scrubbed by the same processor, but the real fix for PII
  in metrics is never putting user data in labels (it's also a cardinality bug).
- Scrubbing at the gateway doesn't help data that bypasses it. NetworkPolicy
  should allow OTLP egress from workloads only to the Collector.

## Scrape and write authentication

- ServiceMonitors here scrape over plain HTTP inside the cluster, which is
  common for `/metrics` on a pod network with NetworkPolicy. For sensitive
  metrics, serve `/metrics` with TLS and use the ServiceMonitor's
  `tlsConfig` and `authorization` (credentials from a Secret).
- Collector exporters to Prometheus / Loki / Tempo use placeholders. In a real
  setup, credentials come from environment variables set from an externally
  managed Secret (`${env:LOKI_TOKEN}` in the config), never from the ConfigMap.
  For managed services, use workload identity (for AWS: SigV4 with IRSA or Pod
  Identity for Amazon Managed Service for Prometheus).
- The Collector pod runs as non-root with a read-only root filesystem, no
  capabilities and no service-account token.

## Alerting secrets

The `AlertmanagerConfig` only references `alertmanager-receivers` keys (PagerDuty
routing key, ticket and heartbeat webhook URLs). Webhook URLs often embed a
token, so they are treated as secrets too (`urlSecret`, not `url`). The chart
creates no Secret; a test checks there is no `url:` and no `kind: Secret`.

## Multi-tenancy

- Rules and alerts carry `service`, `slo` and `team` labels; routing and
  silences should be scoped by them, so one team can't silence another's SLOs
  by accident.
- With the operator, a namespaced `AlertmanagerConfig` gets a `namespace`
  matcher. That isolates teams, but alerts from recording rules have no
  namespace label. This project uses one global config; per-team configs would
  need the generator to add a `namespace` label to every rule.
- For hard isolation (separate customers or business units) use a
  multi-tenant backend: Mimir / Cortex / Loki / Tempo with the `X-Scope-OrgID`
  header set per tenant in the Collector, or separate managed workspaces.
- Grafana: one folder per team with folder permissions; dashboards are
  provisioned read-only (`allowUiUpdates: false`) so the generated source stays
  the truth.

## Local demo

Ports bind to 127.0.0.1. Grafana allows anonymous Viewer access and keeps the
default admin account; acceptable for a laptop demo, not for anything shared.
