# Operations

All commands run from `projects/ai-cloud-operations/` with Python 3.11+ and
no extra packages.

## Running the pipeline

```bash
python3 -m aiops generate --out sample-data            # regenerate synthetic data (seed 11)
python3 -m aiops run --out out                         # analyze + correlate + summarize + propose
python3 -m aiops run --out out --format json           # machine-readable, for piping into other tools
python3 -m aiops approve --out out --id <id> --actor you@example.com
python3 -m aiops reject  --out out --id <id> --actor you@example.com --reason "not needed"
python3 -m aiops audit   --out out                     # print the append-only audit log
```

`run` writes two files under `--out` (default `out/`):

| File | Written by | Append-only? |
|---|---|---|
| `audit.jsonl` | every `run` (one "proposed" line per proposal), `approve`, `reject` | yes — see `docs/security.md` |
| `proposals.json` | every `run` (overwritten); `approve`/`reject` update a record's `status` | no, it's a convenience cache, not the audit trail |

## Options

| Option | Default | Meaning |
|---|---|---|
| `--input DIR` | `sample-data` | directory with `logs.jsonl`, `deploys.jsonl`, `alerts.jsonl` |
| `--logs / --deploys / --alerts FILE` | - | override individual files |
| `--window-minutes` | `5` | bucket width for the error-rate time series |
| `--baseline-windows` | `12` | trailing buckets used for the rolling mean/stddev |
| `--z-threshold` | `3.0` | minimum z-score to flag a bucket as anomalous |
| `--min-events` | `5` | minimum events in a bucket before it is scored |
| `--correlation-window-minutes` | `15` | +/- window for matching deploys/alerts to an anomaly |
| `--use-llm` | off | enable the optional summary step (default provider is a no-op; see below) |
| `--token-budget` | `400` | cap passed to the LLM provider as a max-output-tokens hint |
| `--format text\|json\|markdown` | `text` | output format for `run` |

## The `--use-llm` flag, precisely

Passing `--use-llm` does **not** make a network call by default: the CLI
always constructs `NoOpLLMProvider` (see `aiops/llm.py`), which returns
`None` and `summarize()` falls back to the template. The flag exists so the
redaction + prompt-budgeting code path (`aiops/summarize.py`) runs in CI and
in the sample output below, without ever needing an API key. To use a real
provider, you would import your own `LLMProvider` implementation and pass
`SummaryConfig(provider=YourProvider(...))` to `aiops.pipeline.run()` from
Python — there's no CLI flag to inject an arbitrary provider class, by
design, so running the published CLI can never silently add an external
call.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Input error (missing/malformed file, unknown proposal id, disallowed approval) |
| 2 | Command-line usage error (argparse) |

## Tests and validation

```bash
python3 -m unittest discover -s tests -v
```

## Regenerating sample data

```bash
python3 -m aiops generate --out sample-data --seed 11
git diff --stat sample-data   # should be empty unless the generator changed
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `error: sample-data/logs.jsonl: file not found` | running outside the project dir; `cd projects/ai-cloud-operations` or pass `--input` |
| `error: ...: timestamp '...' has no timezone` | log/deploy/alert timestamps must be ISO-8601 with `Z` or an explicit offset |
| `error: no pending proposal '<id>' in out/proposals.json` | `approve`/`reject` must point `--out` at the same directory `run` used, and the id must come from that run's output |
| `error: action 'X' is not on the remediation allow-list...` | `approve` refuses proposals where `allowed` is `False`; such a proposal can be rejected or left pending, never approved |
| No anomalies found on real data | raise/lower `--z-threshold`, check `--window-minutes`/`--baseline-windows` match your traffic's natural cadence, and confirm `level` values map to `ERROR_LEVELS` in `aiops/anomaly.py` |
