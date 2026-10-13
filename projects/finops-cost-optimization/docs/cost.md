# Cost of the guardrails themselves

A cost-control stack shouldn't become a line item worth optimising. These
are illustrative, approximate us-east-1 list prices as understood at the time
of writing. **Verify against current AWS pricing**; nothing in this repo has
been deployed or billed.

| Component | Pricing model | Expected cost for this module |
|---|---|---|
| AWS Budgets (`aws_budgets_budget`) | Monitoring-only budgets have historically been free or a few cents per budget-day beyond a small free allowance; budget *actions* are billed separately. Check the AWS Budgets pricing page | ~$0 for one budget without actions |
| Cost Anomaly Detection (monitor + subscription) | No charge | $0 |
| SNS topic + email deliveries | First 1,000 email notifications/month free | ~$0 at alert volumes |
| KMS customer-managed key (alerts topic) | ~$1 per key-month plus per-request charges (well inside the free tier at alert volume) | ~$1/month |
| BCM Data Exports (FOCUS) | No charge for the export itself; you pay for S3 storage and requests | $0 + S3 |
| S3 export bucket | ~$0.023/GB-month Standard plus PUT/GET requests | Cents to a few dollars per month |

## S3 storage drivers

- **Export size** scales with resource count and granularity. A small account
  produces a few MB of gzip CSV per month; large estates with `ResourceId`
  granularity reach GBs.
- **Overwrite vs create-new.** The module sets `OVERWRITE_REPORT`, so each
  refresh replaces the current month's files instead of piling up copies.
  Versioning is still on for safety, so overwritten versions are noncurrent
  and expire after 30 days by lifecycle rule.
- **Retention.** `export_retention_days` defaults to 400 so you can compare
  year over year. Lowering it saves storage; raising it is cheap at gzip-CSV
  sizes.
- **Requests.** The toolkit syncs a handful of objects per run, which is
  negligible.

## What would make it expensive

- Switching the bucket to SSE-KMS with a customer-managed key **without** S3
  bucket keys means one KMS request per object operation. The module enables
  bucket keys.
- Querying the export with Athena over uncompressed CSV scans every byte. For
  ad-hoc SQL, export Parquet as well and partition by billing period.
- Many budgets with actions beyond the free allowance.

## The toolkit

The Python toolkit runs locally or in CI and calls no AWS APIs. Its cost is
CI minutes: the GitHub Actions workflow finishes in well under a minute of
compute on the sample data. The Terraform job's provider download takes the
longest.
