# Security

## The analysis process cannot act on a system — only propose

`aiops` never imports, configures, or has any code path to an SSH client,
a Kubernetes/cloud SDK, or any other mechanism capable of restarting a pod,
scaling a service, or rolling back a deploy. The allow-list in
`aiops/remediation.py` (`ALLOWED_ACTIONS`) is a set of **names and
descriptions only**. `propose()` returns a `Proposal` dataclass; nothing in
this codebase accepts a `Proposal` and executes it. Wiring a real executor
would be a deliberate, separate integration with its own credentials and
its own audit trail — out of scope here on purpose, so that the pipeline
that reads your logs never needs write access to your infrastructure.

## No external calls or API keys by default

The `LLMProvider` interface (`aiops/llm.py`) defaults to `NoOpLLMProvider`,
which returns `None` and performs no I/O. `aiops run` without `--use-llm`
never constructs a provider that could call out, and even with `--use-llm`
the default provider still makes no network call — it exists so the
redaction and prompt-budgeting code paths are exercised in CI without
needing a real key. See [`docs/architecture.md`](architecture.md) for how a
real provider would be plugged in: it is a one-class addition at the call
site, never a change to the pipeline itself.

## Redaction before any external call

`aiops/redact.py` runs on any raw log excerpt before it is placed in an
LLM prompt (`aiops/summarize.py::summarize`), regardless of which provider
is configured. It masks:

| Pattern | Example | Replacement |
|---|---|---|
| Email addresses | `alice@example.com` | `[REDACTED_EMAIL]` |
| IPv4 addresses | `203.0.113.42` | `[REDACTED_IP]` |
| `key=value` / `key: value` pairs that look like credentials (`token`, `secret`, `password`, `api_key`, ...) | `token=abcdef123456` | `token=[REDACTED_SECRET]` |
| Bare provider-shaped tokens | `ghp_...`, `sk-...`, `xoxb-...` | `[REDACTED_SECRET]` |

This is a basic, auditable guardrail (`tests/test_redact.py`), not a
general PII/DLP engine. Treat it as a floor, not a substitute for not
logging secrets in the first place.

## Audit log integrity

`aiops/audit.py::AuditLog` only ever opens its file in append (`"a"`) mode
and never seeks or rewrites it. Every proposal the pipeline produces and
every human decision (`approve` / `reject`) is one JSON line with a UTC
timestamp, an actor, the proposal id, the service and the action — enough
to reconstruct who approved what, and when, without re-running the
pipeline. `AuditLog.approve()` additionally refuses (raises
`RemediationNotAllowed`) if the proposal's action isn't on the allow-list,
so an out-of-policy action can be reported but never recorded as approved.

In this portfolio implementation the audit file is a local JSONL file with
OS file permissions as its only protection. A production deployment should
ship it to a write-once destination (e.g. an object store with Object Lock,
or a dedicated audit service) rather than relying on local append-only
semantics alone, and restrict who can run the `approve`/`reject` commands
(e.g. require the `--actor` identity to come from an authenticated
session, not a free-text flag).

## Threats considered

| Threat | Mitigation |
|---|---|
| The pipeline executes a remediation action itself | No code path exists to do so; `propose()` only returns data |
| An unreviewed/unknown action gets recorded as approved | `AuditLog.approve()` raises `RemediationNotAllowed` for `allowed=False` proposals |
| Secrets in log messages reach an LLM provider | `redact()` runs before every prompt is built, regardless of provider |
| Unbounded or surprise spend from the LLM step | `token_budget` caps the requested output size; `use_llm` is off by default; see [the README's cost section](../README.md#cost) |
| A single noisy bucket causes a false "anomaly" | `min_events` floor and the z-score threshold (see `docs/architecture.md`) |
| Tampering with the audit trail after the fact | Append-only file handling in this codebase; ship to a write-once store in production (see above) |
