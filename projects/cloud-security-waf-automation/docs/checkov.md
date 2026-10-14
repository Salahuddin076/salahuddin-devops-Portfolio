# Running Checkov against the same Terraform

Checkov isn't installed or required for this project, and the commands below
weren't run for this repo. They're the off-the-shelf alternative discussed in
[ADR 0002](decisions/0002-stdlib-policy-checker-vs-opa-checkov.md).

## Install (isolated)

```bash
python3 -m venv .venv-checkov && . .venv-checkov/bin/activate
pip install checkov          # pin a version in CI, e.g. checkov==3.x.y
```

## Scan the Terraform source

```bash
cd projects/cloud-security-waf-automation
checkov -d terraform --framework terraform --compact
```

## Scan a plan (what check_plan.py does)

Plan scanning sees resolved values. It needs a real plan, so credentials, so
it's not done in this repo:

```bash
terraform -chdir=terraform/examples/basic plan -out tfplan
terraform -chdir=terraform/examples/basic show -json tfplan > plan.json
checkov -f plan.json --framework terraform_plan
```

The synthetic fixtures are in the same `terraform show -json` shape, so they
can be scanned the same way:

```bash
checkov -f policy/fixtures/plan-noncompliant.json --framework terraform_plan --compact
```

## SARIF for code scanning

```bash
checkov -d terraform --framework terraform -o sarif --output-file-path reports/
# -> reports/results_sarif.sarif, upload with github/codeql-action/upload-sarif@v3
```

## Rough mapping to this project's rules

Check IDs change between Checkov releases. Confirm them with
`checkov --list | grep -i <keyword>` before relying on this table.

| check_plan rule | What to look for in Checkov |
|---|---|
| CSP-S3-001 public access block | S3 public access block checks (block public ACLs/policy, ignore ACLs, restrict buckets) |
| CSP-SG-001 open 22/3389 | "security group allows ingress from 0.0.0.0/0 to port 22 / 3389" |
| CSP-IAM-001 `*` on `*` | IAM policies allowing full administrative privileges |
| CSP-RDS-001 encryption | RDS / Aurora storage encryption |
| CSP-CT-001 log validation | CloudTrail log file validation |
| CSP-WAF-001 ALB without WAF | Public ALB protected by WAF |

## Skips with an expiry

Checkov supports inline skips (`#checkov:skip=CKV_AWS_XXX:reason`) and
`--skip-check`, but has no built-in expiry. To keep this project's
discipline (owner, reason and expiry date), keep the exceptions in a file
like `policy/exceptions.json` and generate the skip list from it in CI,
failing the job when an entry has expired.
