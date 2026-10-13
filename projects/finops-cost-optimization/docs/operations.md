# Operations

All commands run from `projects/finops-cost-optimization/` with Python 3.11+
and no extra packages.

## Running the toolkit

```bash
python3 -m finops generate --out sample-data          # regenerate synthetic data (seed 42)
python3 -m finops allocate                            # showback by team/env/app
python3 -m finops rightsize                           # idle / downsize / Graviton / EBS
python3 -m finops commitments --percentile 20 --discount 0.28
python3 -m finops forecast --horizon 30 --lookback 60
python3 -m finops budget --budget 6500                # exit 3 on breach
python3 -m finops report --budget 6500 --out out --html
```

Common options (every analysis command):

| Option | Default | Meaning |
|---|---|---|
| `--input DIR` | `sample-data` | Directory holding `billing.csv`, `utilization.csv`, `ebs_volumes.csv` |
| `--billing / --utilization / --volumes FILE` | - | Override individual files |
| `--format text\|json\|markdown` | `text` | `json` is stable for piping into other tools |
| `--cost-column effective\|billed` | `effective` | Amortised (showback) vs invoice view |

Tuning knobs: `rightsize --idle-cpu 5 --downsize-cpu 40 --max-projected-cpu 70
--no-graviton`; `commitments --percentile 20 --discount 0.28
--eligible-service "Amazon EC2"` (repeatable); `budget --thresholds 80,100
--fail-at 100 --measure forecast|actual --as-of YYYY-MM-DD --lookback 30`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (and, for `budget`, no gate breach) |
| 1 | Input error: missing file, missing column, bad value (message includes `file:line`) |
| 2 | Command-line usage error (argparse) |
| 3 | `budget` only: the chosen measure reached `--fail-at` percent of the budget |

### Using the budget gate in CI

```yaml
- name: Budget gate
  working-directory: projects/finops-cost-optimization
  run: python3 -m finops budget --input data --budget 6500 --fail-at 100 --measure forecast
```

Lower thresholds (e.g. 80%) are printed as warnings but don't fail the job.
Use `--measure actual` to fail only once real spend crosses the line.

## Plugging in a real FOCUS export

The Terraform module creates a BCM Data Export of the `FOCUS_1_0_AWS` table
as gzip CSV under `s3://<prefix>-billing-exports-<account>/focus/`. AWS
writes the first export within 24 hours and refreshes it during the month.

1. Assume the read-only role from [security.md](security.md) and sync the
   current billing period:

   ```bash
   aws s3 sync "s3://example-billing-exports/focus/" ./data/raw/ --exclude "*" --include "*.csv.gz"
   ```

2. Concatenate into one CSV with a single header (stdlib only):

   ```bash
   python3 - <<'PY'
   import csv, glob, gzip
   files = sorted(glob.glob("data/raw/**/*.csv.gz", recursive=True))
   with open("data/billing.csv", "w", newline="") as out:
       writer = None
       for path in files:
           with gzip.open(path, "rt", newline="") as fh:
               reader = csv.DictReader(fh)
               if writer is None:
                   writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
                   writer.writeheader()
               writer.writerows(reader)
   PY
   ```

3. Run `python3 -m finops report --input data --budget <amount> --out out --html`.

Column mapping notes:

| Toolkit expects | Real FOCUS 1.0 export | Notes |
|---|---|---|
| `ChargePeriodStart/End`, `ServiceName`, `BilledCost`, `EffectiveCost` | same | Required |
| `ListCost` | same | Used for coverage %; falls back to `EffectiveCost` when absent |
| `UsageQuantity` | `ConsumedQuantity` | Either is accepted |
| `PricingCategory` `On-Demand` | `Standard` / `Dynamic` | Anything other than `Committed` is treated as on-demand |
| `ChargeCategory` | `Usage`, `Purchase`, `Tax`, `Credit`, `Adjustment` | Only `Usage` rows feed the commitment baseline |
| `Tags` (JSON object) | `Tags` | Only cost allocation tags that are **activated** in Billing appear |
| `x_InstanceType` | not present | Optional; rightsizing uses `utilization.csv` |
| `ServiceName` `Amazon EC2` | `Amazon Elastic Compute Cloud` | Pass `--eligible-service "Amazon Elastic Compute Cloud"` to `commitments` |

Real FOCUS exports also put EBS and NAT under the EC2 service name. Filter
commitment eligibility on `ResourceType`/`x_UsageType` before trusting the
coverage number. That is a known gap; see limitations in the README.

Utilization and volume inventory aren't in the billing export:

- `utilization.csv`: from CloudWatch `CPUUtilization` (Average and p95 over
  14+ days) plus memory from the CloudWatch agent (`mem_used_percent`).
  Without the agent, leave memory at a conservative value such as `100` so no
  instance gets downsized on CPU alone. AWS Compute Optimizer exports work as
  a cross-check.
- `ebs_volumes.csv`: `aws ec2 describe-volumes` (`State`, `Size`,
  `VolumeType`, `Attachments`). `days_in_state` comes from AWS Config history
  or your own tagging (`detached-at`).

## Regenerating sample data

```bash
python3 -m finops generate --out sample-data --seed 42 --start 2026-07-01 --days 90
git diff --stat sample-data   # should be empty unless the generator changed
```

## Tests and validation

```bash
python3 -m unittest discover -s tests -v
cd terraform && terraform fmt -check -recursive
terraform -chdir=modules/cost-guardrails init -backend=false && terraform -chdir=modules/cost-guardrails validate
terraform -chdir=examples/basic init -backend=false && terraform -chdir=examples/basic validate
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `error: sample-data/billing.csv: file not found` | Running outside the project dir; `cd projects/finops-cost-optimization` or pass `--input` |
| `missing required column(s): ChargePeriodEnd` | Export is CUR 2.0 rather than FOCUS, or columns were renamed. Re-export `FOCUS_1_0_AWS` or rename headers |
| `billing.csv:1234: Expecting property name...` | `Tags` cell isn't valid JSON. Check quoting from whatever concatenated the files |
| `no eligible usage for services ['Amazon EC2']` | Service name differs in real exports; pass `--eligible-service` |
| Untagged % is ~100% on real data | Cost allocation tags aren't activated in Billing, or were activated recently (not retroactive) |
| Forecast looks wrong right after a migration | OLS follows the step change slowly; shorten `--lookback` or wait for the window to roll past it |
| Budget gate fails on day 1-3 of the month | Only a few days of history in the month; consider `--measure actual` early in the month |
| `terraform init` is slow | First provider download is large; set `TF_PLUGIN_CACHE_DIR` |
| Anomaly monitor create fails with a limit error | The account already has an AWS-services monitor; set `existing_anomaly_monitor_arn` |
| No email alerts | Each SNS email subscription must be confirmed from the inbox |
