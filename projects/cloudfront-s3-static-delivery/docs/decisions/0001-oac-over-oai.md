# ADR 0001: Origin Access Control instead of Origin Access Identity or a public website bucket

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** cloudfront-s3-static-delivery (portfolio implementation)

## Context

The site's files live in S3, and CloudFront must be the only way to read
them. Otherwise the WAF, the security headers, HTTPS enforcement and access
logs can all be bypassed with a direct bucket URL. There are three ways to
connect CloudFront to S3:

1. **A public S3 website endpoint** as a custom origin. It needs a public
   bucket policy, serves HTTP only from S3, and anyone can skip CloudFront.
   (A secret `Referer` header is a shared-secret workaround, not access
   control.)
2. **Origin Access Identity (OAI)**: a special CloudFront principal granted
   in the bucket policy. AWS now calls it legacy. It doesn't support SSE-KMS
   objects, opt-in regions launched after 2022, or signed requests for
   PUT/POST/DELETE, and its principal isn't tied to a particular
   distribution.
3. **Origin Access Control (OAC)**: CloudFront signs origin requests with
   SigV4 as the `cloudfront.amazonaws.com` service principal, and the
   bucket policy pins access to one distribution with `AWS:SourceArn`.

## Decision

Use OAC (`aws_cloudfront_origin_access_control`, origin type `s3`,
`signing_behavior = "always"`, SigV4) on the bucket's REST endpoint.

- The bucket stays fully private: all four public-access blocks, ACLs
  disabled, no website hosting configuration.
- The bucket policy allows only `s3:GetObject`, only for
  `cloudfront.amazonaws.com`, only with `AWS:SourceArn` equal to this
  distribution's ARN. It also denies non-TLS access.
- The distribution doesn't get `s3:ListBucket`, so missing keys return
  403. They're mapped to `/404.html` with status 404.
- Directory indexes, which the website endpoint used to provide, move to
  a CloudFront Function ([ADR 0002](0002-cloudfront-functions-vs-lambda-edge.md)).

## Consequences

- A direct request to the bucket is refused, so every request goes
  through CloudFront's controls.
- SSE-KMS works, at the cost of a key-policy grant for
  `cloudfront.amazonaws.com`. The module outputs the statement. SSE-S3 is
  the default so the common case needs no grant.
- The bucket policy depends on the distribution ARN, and the distribution
  depends on the bucket's domain name. Terraform resolves this by creating
  the policy after the distribution, so for a minute during the first
  apply, CloudFront exists but can't read the bucket (nothing is published
  yet anyway).
- Recreating the distribution changes its ARN. Terraform updates the
  policy in the same apply, but a manual recreation would break access
  until the policy is fixed ([operations](../operations.md#403-accessdenied-on-every-request)).
- We lose the website endpoint's built-in redirect rules. The function
  handles the one redirect this site needs (missing trailing slash).
