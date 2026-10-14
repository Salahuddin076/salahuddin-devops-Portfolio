# Operations

> Working portfolio implementation. These procedures follow AWS
> documentation and the module's design; none has been run against a real
> account from this repo.

## First deploy

Prerequisites: a public Route 53 hosted zone for the domain, already
delegated from the registrar (`dig NS example.com` returns the zone's name
servers). Without delegation, ACM never sees the validation records and
the apply waits on the certificate until it times out.

1. **Apply the stack** (`terraform/examples/basic`, with real values in a
   private tfvars). Terraform orders it as follows:
   1. the bucket and its controls, the OAC, the function, the headers policy;
   2. the ACM certificate in us-east-1, then the validation CNAMEs in the zone;
   3. `aws_acm_certificate_validation` waits for ISSUED, usually a few
      minutes after the records resolve (the default timeout is 75 minutes);
   4. the distribution (several minutes to deploy to all edges);
   5. the bucket policy (it needs the distribution ARN), the alias records,
      and the log delivery.
2. **If the account already has a GitHub OIDC provider**, set
   `existing_oidc_provider_arn`. Creating a second one fails with
   `EntityAlreadyExists`.
3. **Test on the CloudFront name first:**
   `curl -sSI https://<distribution_domain_name>/` should return 200 with the
   security headers. A certificate error on that name is normal (it serves
   the custom certificate for your aliases); use `curl -k` here only.
4. **Upload the site** (the first deploy has an empty manifest):

   ```bash
   aws s3api list-objects-v2 --bucket "$BUCKET" --output json > remote.json
   python3 scripts/deploy_plan.py site --manifest remote.json > plan.json
   # then upload, delete and invalidate as in the workflow's deploy-example job
   ```

5. **Check the real hostname:**

   ```bash
   curl -sSIL https://www.example.com/docs > headers.txt
   python3 scripts/check_headers.py headers.txt
   ```

   `-L` follows the function's 301 to `/docs/`; the checker reads the last
   response.

### Enabling the deploy job

The workflow's `deploy-example` job is disabled with `if: false` and never
runs. To enable it after the stack exists:

1. Create the `production` environment in the repository settings, with
   required reviewers and a `main`-only deployment branch rule.
2. Add repository variables from the Terraform outputs:
   `STATIC_SITE_DEPLOY_ROLE_ARN`, `STATIC_SITE_BUCKET`,
   `STATIC_SITE_DISTRIBUTION_ID`. They are not secrets.
3. Remove the `if: false` line in a reviewed pull request.

## Rollback

The bucket is versioned, and the lifecycle rule keeps replaced and deleted
versions for 30 days (and always the newest 3). Rolling back means making
the previous version of each changed object current again, then
invalidating.

The deploy role cannot do this on purpose: it has no `s3:GetObjectVersion`
or `s3:ListBucketVersions`. Rollback is an operator action with a separate
role.

1. **Find what the bad deploy changed.** Keep each deploy's `plan.json` as
   a workflow artifact. Its `upload` and `delete` lists are the rollback
   scope.
2. **Restore each object's previous version** by copying it over the
   current one, which creates a new current version with the old content
   (history is preserved, and the copy keeps the old `Cache-Control`):

   ```bash
   key=index.html
   prev=$(aws s3api list-object-versions --bucket "$BUCKET" --prefix "$key" \
     --query "Versions[?Key=='$key'] | sort_by(@, &LastModified) | [-2].VersionId" --output text)
   aws s3api copy-object --bucket "$BUCKET" --key "$key" \
     --copy-source "$BUCKET/$key?versionId=$prev" --metadata-directive COPY
   ```

   For an object the bad deploy **deleted**, remove the delete marker
   instead: `aws s3api delete-object --bucket "$BUCKET" --key "$key"
   --version-id <delete-marker-id>`.
   For an object it **added**, delete it.
3. **Invalidate** the same paths `deploy_plan.py` would have computed:
   the changed non-hashed objects (with `/dir/` next to `/dir/index.html`),
   or `/*` if there are many. Hashed assets need nothing: the restored
   HTML points at the old hashes, which are still in the bucket (the
   workflow deploys with `--keep-old-hashed`) or restorable the same way.
4. Re-run `check_headers.py` and spot-check the pages.

Rolling forward (reverting the commit and letting the pipeline deploy) is
usually simpler and leaves an audit trail in git. Restoring versions is for
when the pipeline itself is broken.

## Troubleshooting

### 403 AccessDenied on every request

Usually OAC, in this order of likelihood:

- **The bucket policy's `AWS:SourceArn` does not match the distribution.**
  It happens after a distribution is recreated, or when a policy is copied
  from another stack. Compare `terraform output distribution_arn` with the
  policy.
- **The origin uses the S3 website endpoint** (`*.s3-website-*`). OAC only
  signs requests to the REST endpoint (`bucket_regional_domain_name`).
- **A legacy OAI is still configured** on the origin alongside OAC. Remove
  `s3_origin_config`.
- **The object really is missing.** Without `s3:ListBucket`, S3 returns
  403 for a missing key. That is expected, and the distribution maps it to
  `/404.html` with status 404. If you see a raw 403 XML body, the custom
  error response is not deployed yet.

### 403 only on some objects: KMS

- The bucket uses SSE-KMS and the **key policy** does not allow
  `cloudfront.amazonaws.com` to `kms:Decrypt` with `AWS:SourceArn` equal to
  the distribution. The bucket policy is not enough: KMS checks its own
  policy. Add the statement from the `kms_key_policy_statement` output.
- Objects uploaded before a key change are still encrypted with the old
  key. Re-copy them, or grant both keys.
- With SSE-KMS, S3 ETags are not MD5s, so `deploy_plan.py` reports every
  file as changed. Uploads are correct but not minimal. This is one more
  reason SSE-S3 is the default.

### Stale content after a deploy

- **HTML still old:** check the object's `Cache-Control` with
  `aws s3api head-object`. It must be `no-cache`. A manual `aws s3 cp`
  without `--cache-control` leaves no header, and CloudFront then uses the
  policy's default TTL of one day. Fix the header, then invalidate.
- **The browser holds it, not CloudFront:** if `x-cache: Hit from
  cloudfront` shows the new ETag, it is the browser. Hashed assets are
  `immutable` by design; their file names must change when content does.
- **The invalidation path doesn't match the cache key:** the function
  rewrites before the cache, so the key for `/docs/` is
  `/docs/index.html`. The plan invalidates both forms. Paths are
  case-sensitive and must be URL-encoded.
- **Invalidation still in progress:** `aws cloudfront get-invalidation`
  (an operator permission; the deploy role only creates them). They
  usually complete within minutes.

### Wrong region: certificate or WAF

- **Certificate not selectable, or `InvalidViewerCertificate`:** it was
  issued outside us-east-1. CloudFront only reads ACM in us-east-1. The
  module issues it through `aws.us_east_1` and its `check` block fails the
  plan if that alias is in another region.
- **`WAFNonexistentItemException` or an invalid web ACL on the
  distribution:** the ACL is REGIONAL or in another region. CloudFront
  needs a CLOUDFRONT-scope ACL, which AWS only creates in us-east-1 (its
  ARN contains `:us-east-1:` and `global/webacl`). The `web_acl_arn`
  validation rejects anything else.
- **No access logs arrive:** the delivery source for a distribution must be
  in us-east-1, and so is the log group. Look in us-east-1, not the bucket's
  region.

### The deploy job can't assume the role

`Not authorized to perform sts:AssumeRoleWithWebIdentity` almost always
means the token's `sub` isn't in the trust policy:

- the job declares `environment:`, so `sub` is
  `repo:<org>/<repo>:environment:<name>`, but only the branch is trusted
  (or the other way round);
- the workflow ran on a branch other than `main`, a tag or a pull request;
- the repository was renamed or transferred. `sub` uses the current
  `<org>/<repo>`.

The `allowed_subjects` output lists exactly what is trusted. Also check that
the job has `permissions: id-token: write`; without it no token is issued at
all.
