# ADR 0003: Scrub PII in the OpenTelemetry Collector gateway

**Status:** accepted

## Context

Traces and logs end up holding personal data: `Authorization` headers
recorded by HTTP instrumentation, cookies, user attributes added by
developers, e-mail addresses in URLs. Once stored in Loki or Tempo, it is
replicated, retained and visible to everyone with dashboard access, and
deleting it on request is hard.

Options:

1. Rely on every service's instrumentation to never record PII.
2. Scrub in each service's SDK (span processors).
3. Scrub centrally in a Collector gateway that all OTLP traffic passes through.
4. Scrub at the backend (ingest-time pipelines), if supported.

## Decision

Option 3, with option 1 as the expectation:

- One Collector deployment (`helm/observability-stack`) with
  `memory_limiter -> attributes/scrub-pii -> transform/strip-query -> batch`
  in every pipeline.
- **delete** credentials, cookies, e-mail, phone, full name, and any attribute
  whose key matches `password|passwd|secret|token|api_key`;
- **hash** stable identifiers (`enduser.id`, `user.id`, `client.address`) so
  joins across traces and logs still work;
- strip query strings from URL attributes.

Low-entropy values (e-mail, phone) are deleted, not hashed: an unsalted hash
of an e-mail address can be reversed by hashing candidates.

## Consequences

- One place to review and change; a new rule applies to every service at once.
- It only works if traffic can't bypass the gateway: NetworkPolicy should
  restrict OTLP egress to the Collector.
- Attribute rules don't inspect free-text log bodies; that stays a source-code
  responsibility (structured logging), or an extra regex transform with a CPU cost.
- Hashed IDs are pseudonymous, still personal data under most privacy laws:
  retention and access controls still apply.
- Verified: the config passes `otelcol-contrib validate` (0.130.0), which builds
  every pipeline, and the tests check that every pipeline references defined
  components and has the processors in this order.
