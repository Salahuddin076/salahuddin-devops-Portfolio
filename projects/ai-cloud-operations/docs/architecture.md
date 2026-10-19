# Architecture

## Pipeline stages

```mermaid
flowchart LR
  subgraph Inputs
    LOGS["logs.jsonl"]
    DEPLOYS["deploys.jsonl"]
    ALERTS["alerts.jsonl"]
  end
  subgraph Analyze["Analyze (deterministic)"]
    AN["anomaly.detect()<br/>rolling baseline z-score"]
    CO["correlation.correlate()<br/>time window + service"]
  end
  subgraph Summarize
    TPL["summarize.template_summary()<br/>always runs"]
    RED["redact.redact()"]
    LLM["llm.LLMProvider<br/>NoOpLLMProvider by default"]
  end
  subgraph Act
    PROP["remediation.propose()<br/>allow-listed action names"]
    APPR{{"human approve/reject<br/>(CLI: aiops approve/reject)"}}
    AUDIT[("audit.jsonl<br/>append-only")]
  end

  LOGS --> AN
  AN --> CO
  DEPLOYS --> CO
  ALERTS --> CO
  CO --> TPL
  CO -. raw excerpt .-> RED
  RED -. redacted only .-> LLM
  TPL --> PROP
  LLM -. optional override .-> PROP
  CO --> PROP
  PROP -->|"proposed" entry| AUDIT
  PROP --> APPR
  APPR -->|"approved" or "rejected" entry| AUDIT
```

The LLM box is dashed because it is optional and, by default
(`NoOpLLMProvider`), never runs a network call — `summarize()` always falls
back to the template path. The arrow from `Act` to a real system is
deliberately absent: `propose()` returns a `Proposal` object and nothing in
this codebase executes it.

## Modules

| Module | Responsibility |
|---|---|
| `aiops/models.py` | Frozen dataclasses for every stage's input/output (`LogEvent`, `Anomaly`, `Correlation`, `Summary`, `Proposal`, `AuditEntry`) |
| `aiops/anomaly.py` | Rolling-baseline z-score over per-service error rate, bucketed by time window |
| `aiops/correlation.py` | Match anomalies to deploys/alerts by time window + service |
| `aiops/redact.py` | Regex-based redaction (emails, IPv4, credential-shaped key=value pairs, bare provider tokens) |
| `aiops/llm.py` | `LLMProvider` protocol + `NoOpLLMProvider`; documents how a real provider plugs in |
| `aiops/summarize.py` | Always-on template summary; optional, budgeted, redacted LLM summary |
| `aiops/remediation.py` | Allow-listed action registry + `propose()`; never executes anything |
| `aiops/audit.py` | Append-only JSONL audit log; `approve()` refuses non-allow-listed actions |
| `aiops/proposals_store.py` | Mutable convenience cache of *pending* proposals for the CLI (not the audit trail) |
| `aiops/pipeline.py` | Orchestrates Analyze -> Summarize -> Act and records "proposed" entries |
| `aiops/io.py` | JSONL readers/writers for logs, deploys, alerts |
| `aiops/generator.py` | Deterministic synthetic sample data (seeded) |
| `aiops/cli.py` | `generate` / `run` / `approve` / `reject` / `audit` subcommands |

## Why deterministic analysis comes first

Correlating a spike with a deploy that landed four minutes earlier doesn't
need a model — it needs a sorted timestamp comparison. Running the cheap,
explainable method first means:

- The pipeline produces a useful, auditable result with zero API keys and
  zero network calls, which is the default and the common case in CI.
- When an LLM summary is enabled, it is asked to *describe* findings that
  are already computed and already true, not to *decide* whether something
  is anomalous — removing the most consequential class of hallucination risk
  from the loop.
- Every proposal's rationale cites the actual z-score, window and correlated
  events, not model output, so it survives a post-incident review.

## Rolling-baseline anomaly detection, precisely

For each service, log events are grouped into fixed-width time buckets
(default 5 minutes). Each bucket's `error_rate` is `ERROR`-level events
divided by total events in the bucket. For a bucket with at least
`baseline_windows` (default 12, i.e. the trailing hour at 5-minute buckets)
prior buckets, the mean and population standard deviation of `error_rate`
over that trailing window is the baseline. The bucket's z-score is
`(observed - mean) / stddev`; when the baseline has zero variance, a
documented floor (`min_stddev`, default `0.01`) is substituted instead of
dividing by zero. A bucket is an anomaly when `z_score >= z_threshold`
(default `3.0`) and it has at least `min_events` (default `5`) samples, so
a single stray error in an otherwise quiet window isn't reported as a rate
anomaly. See `aiops/anomaly.py` for the full docstring and `tests/test_anomaly.py`
for the edge cases this covers (flat baseline, zero variance, sparse
buckets, insufficient history, multi-service independence).

## Correlation

`correlate()` matches each anomaly to every deploy and alert for the
**same service** whose timestamp falls within `+/- window_minutes` (default
15) of the anomaly's bucket. Both directions are checked because a deploy
just before the bucket is the common "bad rollout" case, and an alert can
fire a little after the bucket starts once a downstream monitor trips.

## Remediation selection (illustrative, not a recommendation engine)

`remediation.propose()` picks one of four allow-listed action **names** —
it never executes them:

1. A correlated deploy -> `rollback-deploy`.
2. No deploy but a correlated alert -> `scale-up`.
3. No correlation, moderate severity (`z < 5.0`) -> `restart-pod`.
4. No correlation, severe (`z >= 5.0`) -> `escalate` (report to a human,
   propose nothing automated).

This is intentionally simple and fully enumerable — the point is that the
decision is traceable to the same statistics already in the summary, not
that it is a sophisticated playbook.
