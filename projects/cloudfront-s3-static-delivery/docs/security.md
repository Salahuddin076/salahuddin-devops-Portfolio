# Security

> Working portfolio implementation. The controls below are configured and
> validated with `terraform validate`; none has been exercised in AWS.

## Threats and controls

| Threat | Control | Where |
|---|---|---|
| Bucket read directly, bypassing CloudFront (and its WAF, headers, logs) | Private bucket: all four public-access blocks, no website endpoint, ACLs disabled (`BucketOwnerEnforced`). The bucket policy allows `s3:GetObject` only to `cloudfront.amazonaws.com` with `AWS:SourceArn` equal to this distribution | `bucket.tf` |
| Another CloudFront distribution reads the bucket (confused deputy) | The `AWS:SourceArn` condition names one distribution. OAC signs with SigV4 on every request (`signing_behavior = "always"`) | `bucket.tf`, `distribution.tf` |
| Object enumeration | The distribution has no `s3:ListBucket`, so a missing key is 403, mapped to `/404.html` with status 404 for every missing path | `distribution.tf` |
| Downgrade or interception | `redirect-to-https`, TLS policy `TLSv1.2_2021` (TLS 1.2+ with forward-secret ciphers only), HSTS for two years with `includeSubDomains`. Origin requests use HTTPS and SigV4. The bucket denies `aws:SecureTransport = false` | `distribution.tf`, `bucket.tf` |
| XSS through injected markup, MIME sniffing, clickjacking, referrer leaks | Response headers policy with `override = true`: a strict same-origin CSP with no `unsafe-inline`, `nosniff`, `X-Frame-Options: DENY` plus `frame-ancestors 'none'`, `strict-origin-when-cross-origin`, and a Permissions-Policy that turns off camera, microphone, geolocation and payment. S3's `x-amz-server-side-encryption` and `x-amz-version-id` headers are stripped | `distribution.tf` |
| Long-lived CI keys leaked | No access keys. GitHub OIDC with short-lived STS credentials (1 hour). The role ARN is a variable, not a secret | `github-oidc-deployer` |
| Any repo, branch or fork deploys | Trust policy: `StringEquals` on `aud = sts.amazonaws.com` and on an exact list of `sub` values, one repository and named branches or environments. No wildcards. The repository format is validated | `github-oidc-deployer` |
| A compromised workflow does more than deploy | The role can list one bucket, put and delete its objects, and create invalidations on one distribution. It cannot read objects, list or delete versions (so it cannot destroy rollback history), change the distribution, or touch IAM | `github-oidc-deployer` |
| Bad or malicious deploy | Versioning and 30 days of noncurrent versions (always the newest 3), so any object can be restored ([operations](operations.md#rollback)). The deploy job requires the `production` environment, which can have required reviewers | `bucket.tf`, workflow |
| Unwatched traffic | Optional CloudFront standard logging v2 to CloudWatch Logs. Optional CLOUDFRONT-scope WAF web ACL | `logging.tf`, `web_acl_arn` |
| Supply chain in the function | The edge code is about 50 lines of dependency-free JS, specified by a tested Python mirror and diffed against it under node in CI | `functions/`, `tests/` |

## Encryption at rest: SSE-S3 by default

The bucket defaults to SSE-S3 (AES256). OAC can read SSE-KMS objects, but
only if the **KMS key policy** lets `cloudfront.amazonaws.com` call
`kms:Decrypt` for this distribution. The bucket policy can't grant that,
and a missing grant shows up as 403 on every object. When `kms_key_arn` is
set, the module:

- switches the default encryption to `aws:kms` with an S3 Bucket Key (fewer
  KMS calls and a lower bill);
- outputs `kms_key_policy_statement`, the exact statement to add to the key
  policy:

  ```json
  {
    "Sid": "AllowCloudFrontOACDecrypt",
    "Effect": "Allow",
    "Principal": { "Service": "cloudfront.amazonaws.com" },
    "Action": ["kms:Decrypt"],
    "Resource": "*",
    "Condition": { "StringEquals": { "AWS:SourceArn": "arn:aws:cloudfront::123456789012:distribution/<ID>" } }
  }
  ```

The module doesn't edit the key policy, because the key usually belongs to
another stack. Pass the same `kms_key_arn` to the deployer module so the
deploy role gets `kms:GenerateDataKey` and `kms:Decrypt` on that key only.

For public website content, a CMK protects little: the content is served to
anyone. It is worth it when policy requires customer-managed keys, or for
key-level audit and revocation.

## Access logging: v2 to CloudWatch Logs, not legacy S3 logging

Legacy CloudFront logging writes to S3 through an ACL grant, so its log
bucket needs ACLs enabled. That contradicts the `BucketOwnerEnforced`
stance everywhere else. Standard logging v2 delivers through CloudWatch
Logs' vended-log mechanism instead. It is authorised by a resource policy
here, scoped to `delivery.logs.amazonaws.com`, with `aws:SourceAccount` and
a `delivery-source` `aws:SourceArn`. The log group gives retention and Logs
Insights with no extra pipeline.

Trade-off: CloudWatch ingestion costs more per GB than S3 at high volume
([cost](cost.md)). Switching the destination to S3 or Firehose is a
change to one resource. Logging is optional (`access_logs = null`). The
delivery source, the destination and the log group must all be in
us-east-1.

Logs contain client IPs and request URIs, which can be personal data, so
retention is bounded (30 days by default).

## GitHub OIDC details

- **One provider per account.** `create_oidc_provider = false` plus
  `existing_oidc_provider_arn` reuses an existing provider instead of
  failing on a duplicate.
- **No thumbprint pinning.** IAM validates GitHub's OIDC endpoint against
  its trusted root CAs, so a pinned thumbprint only adds an outage when
  GitHub rotates certificates.
- **Branch vs environment subject.** A job with `environment: production`
  presents `repo:<org>/<repo>:environment:production`, not the branch
  form. Environment protection rules (required reviewers, allowed
  branches) then act as the approval gate, enforced by GitHub before the
  token is issued.
- **Pull requests can't deploy.** Their `sub` is
  `repo:<org>/<repo>:pull_request`, which is never trusted.
- **Workflow default permissions are `contents: read`.** Only the deploy
  job requests `id-token: write`, and that job is disabled (`if: false`)
  in this repo.

## What isn't covered

- No WAF rules here. Attach a CLOUDFRONT-scope ACL through `web_acl_arn`.
  The cloud-security-waf-automation project's module creates one with
  `scope = "CLOUDFRONT"` through a us-east-1 provider.
- No Subresource Integrity on the demo's assets, and no CSP reporting
  endpoint (`report-to`).
- No CloudTrail data events on the bucket. Enable them centrally if object
  writes need an audit trail beyond the workflow log.
- `hsts_preload` is off by default: getting a domain off the preload list
  takes months.
