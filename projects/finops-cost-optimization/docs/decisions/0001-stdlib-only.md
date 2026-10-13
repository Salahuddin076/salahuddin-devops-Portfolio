# ADR 0001: Python standard library only

- Status: Accepted
- Date: 2026-10-14

## Context

The toolkit has to run in three places: a laptop, a GitHub Actions runner, and
eventually a locked-down environment next to real billing data (a bastion,
a scheduled container, a Lambda). Typical choices are pandas for tables,
numpy for percentiles and regression, and Jinja for reports. Each adds
install time, supply-chain exposure and version drift, and pandas alone is
tens of MB.

The data volumes are small. A month of daily FOCUS rows for a mid-size
account is in the tens of thousands of rows, and the maths is sums,
percentiles and one least-squares line.

## Decision

Use only the Python standard library (`csv`, `json`, `decimal`, `datetime`,
`random`, `argparse`, `html`, `unittest`) and write the small amount of maths
out by hand. No `requirements.txt`.

Money uses `decimal.Decimal` throughout and is rounded half-up to cents only
at presentation boundaries. Regression runs in `float`, because it produces an
estimate, not a ledger figure, and is converted back to `Decimal` for output.

## Consequences

- `python3 -m finops ...` works on any Python 3.11+ with nothing to install. CI
  needs no dependency caching and has no lockfile to maintain.
- Every calculation is visible in about 2,000 lines of plain Python and testable with
  hand-built fixtures, which suits a tool whose output people must trust.
- We wrote small pieces ourselves: percentile with linear interpolation
  (matches numpy's default), OLS, table rendering. Tests pin their behaviour.
- In-memory processing only. Hourly, resource-level exports for large estates
  (millions of rows) would need streaming aggregation or a move to
  DuckDB/Athena. Revisit if a single run exceeds a few hundred MB of input.
- No Parquet reader, so the Terraform export is configured as gzip CSV.
