# Security

Billing data is sensitive. It reveals vendor relationships, architecture,
headcount proxies and, through tags, project names. Treat the export bucket
like any other confidential data store.

## Controls implemented in the Terraform module

| Control | Where |
|---|---|
| All four S3 public-access-block settings enabled | `aws_s3_bucket_public_access_block.exports` |
| Object ownership `BucketOwnerEnforced` (ACLs disabled) | `aws_s3_bucket_ownership_controls.exports` |
| Default encryption SSE-S3 with bucket keys | `aws_s3_bucket_server_side_encryption_configuration.exports` |
| Bucket policy: only `bcm-data-exports` / `billingreports` may write, constrained by `aws:SourceAccount` **and** `aws:SourceArn` (confused-deputy protection) | `data.aws_iam_policy_document.exports_bucket` |
| Deny any non-TLS access to the bucket and the SNS topic | same policies, `aws:SecureTransport = false` |
| Versioning + lifecycle expiry (recover from accidental overwrite, bounded retention) | `aws_s3_bucket_versioning`, `aws_s3_bucket_lifecycle_configuration` |
| SNS topic encrypted with a customer-managed KMS key (rotation on); key policy lets only Budgets and Cost Anomaly Detection use it for this account | `aws_kms_key.alerts` |
| SNS publish restricted to the two cost services from this account | `aws_sns_topic_policy.alerts` |
| No credentials, account IDs or real emails in code; account ID resolved at plan time | `data.aws_caller_identity` |
| Inputs validated (threshold ranges, email format, ARN shape, name pattern) | `variables.tf` |

The bucket uses SSE-S3 rather than SSE-KMS so the export service needs no KMS
grant. If your policy requires customer-managed keys, add a key policy
statement allowing `bcm-data-exports.amazonaws.com` to `kms:GenerateDataKey`
with the same `aws:SourceAccount`/`aws:SourceArn` conditions, and give the
reader role `kms:Decrypt`.

## Least-privilege access for the toolkit

The toolkit only needs to **list and read** export objects. Give CI or analysts
a dedicated role with no write, delete, or billing-console permissions.
Placeholder ARNs below; replace `example-billing-exports` with the bucket
from the `export_bucket_name` output.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListExportPrefixOnly",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::example-billing-exports",
      "Condition": {
        "StringLike": { "s3:prefix": ["focus/", "focus/*"] }
      }
    },
    {
      "Sid": "ReadExportObjects",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::example-billing-exports/focus/*"
    },
    {
      "Sid": "DenyWritesEvenIfGrantedElsewhere",
      "Effect": "Deny",
      "Action": ["s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion", "s3:PutBucketPolicy"],
      "Resource": [
        "arn:aws:s3:::example-billing-exports",
        "arn:aws:s3:::example-billing-exports/*"
      ]
    }
  ]
}
```

For CI, have GitHub Actions assume this role through OIDC
(`token.actions.githubusercontent.com`), with the trust policy's `sub`
restricted to `repo:<org>/<repo>:ref:refs/heads/main`. Don't store access
keys as repository secrets. The workflow in this repo uses synthetic data and
needs no cloud access, so its token is limited to `contents: read`.

Collecting `utilization.csv` and `ebs_volumes.csv` from a real account needs
only `cloudwatch:GetMetricData` and `ec2:DescribeVolumes` /
`ec2:DescribeInstances`. Keep them in a separate role from the billing reader
so read access to costs and to infrastructure metadata can be granted
independently.

## Handling report output

- Reports include resource IDs and tag values. Publish them to an internal
  location, not a public artifact or PR comment on a public repository.
- CI artifacts in this repo are synthetic. On a private repository with real
  data, set a short `retention-days` on the artifact.
- `summary.json` contains all figures. Treat it like the export itself.

## Threats considered

| Threat | Mitigation |
|---|---|
| Bucket made public by mistake | Public access block at bucket level (add the account-level block too) |
| Another account's export writes into the bucket (confused deputy) | `aws:SourceAccount` + `aws:SourceArn` conditions |
| Alert suppression by deleting the topic subscription | SNS changes are visible in CloudTrail; protect with SCPs in production |
| Malicious tag values (HTML/script or spreadsheet formula injection) | HTML report escapes every cell with `html.escape`; Markdown cells escape pipe characters. The toolkit writes CSV only for synthetic data. Don't open real exports in a spreadsheet without sanitising cells that start with `=`, `+`, `-`, `@` |
| Secrets in tag values leaking into reports | Out of scope for the toolkit; enforce tag policies (AWS Organizations tag policies) |
