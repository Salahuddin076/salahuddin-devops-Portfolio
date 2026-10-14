# Cost

> **Illustrative and approximate.** Rounded us-east-1 / North America list
> prices as understood at the time of writing, before the free tier and
> discounts. They are not quotes. CloudFront pricing varies by edge region,
> and AWS also offers flat-rate CloudFront plans, so check the current
> pricing pages. Nothing in this repo has been deployed or billed.

## What drives the bill

| Driver | Pricing basis (approx.) | Lever |
|---|---|---|
| CloudFront data transfer out | ~$0.085/GB for the first 10 TB in North America and Europe; more in other regions | Compression (`compress = true`), long TTLs on hashed assets, `PriceClass_100` |
| CloudFront requests | ~$0.0100 per 10,000 HTTPS requests (North America) | Browser caching: `immutable` assets aren't re-requested at all |
| CloudFront Functions | ~$0.10 per million invocations | It runs on every viewer request, cache hits included, and is still far cheaper than Lambda@Edge ([ADR 0002](decisions/0002-cloudfront-functions-vs-lambda-edge.md)) |
| Invalidations | First 1,000 paths per month free per account, then ~$0.005 per path. A wildcard like `/*` counts as **one** path | See below |
| Origin fetches | S3 GET ~$0.0004 per 1,000. Transfer from S3 to CloudFront is free | A high hit ratio. HTML revalidations are conditional requests |
| S3 storage | ~$0.023/GB-month (Standard), current plus noncurrent versions | The lifecycle rule expires old versions after 30 days |
| Route 53 | ~$0.50 per hosted zone per month. Alias queries to CloudFront are free | Use alias records, not CNAMEs |
| ACM | Public certificates used with CloudFront: no charge | |
| Access logs (optional) | CloudWatch vended-log ingestion ~$0.50/GB (tiered down at volume) + storage ~$0.03/GB-month | 30-day retention, field selection, or an S3 destination at volume |
| WAF (optional) | ~$5 per ACL + ~$1 per rule per month + ~$0.60 per million requests | Only attach one if the site needs it |

## Invalidation: per-path vs wildcard

`deploy_plan.py` lists the exact changed paths and switches to `/*` only
when there would be more than `--threshold` (default 15).

- **Price:** the first 1,000 paths a month are free, and `/*` counts as one
  path. A per-path list of 5 to 15 paths per deploy allows roughly 65 to
  200 free deploys a month. Above the free tier, 15 paths cost ~$0.075 per
  deploy and `/*` costs ~$0.005. So on price alone, a wildcard is never
  worse.
- **Why not always `/*`, then?** Because a wildcard empties the cache for
  *every* object, including hashed assets that didn't change. The next
  viewers at every edge go back to the origin for everything: higher
  latency for them, a burst of origin requests, and a lower hit ratio until
  the cache warms up. A per-path list keeps the 99% of the cache that is
  still correct.
- **Why a threshold?** Past a point, the per-path list buys little (most
  pages changed anyway), risks running into the free-tier limit on busy
  months, and a long `--paths` list is harder to read in a deploy log. The
  default of 15 suits a small site. A docs site that regenerates every page
  on each release would collapse to `/*` anyway.
- **Hashed assets are never invalidated:** a new hash is a new URL, and the
  old one is still correct for any page that references it.

## Example: the demo site

Assumptions: 1 million page views a month, mostly North America and Europe,
~5 requests and ~600 KB transferred per first view (about 300 GB a month
after caching and compression), 20 deploys a month with 10 paths each, and
access logs at ~0.5 KB per request.

| Item | Monthly (approx.) |
|---|---|
| Data transfer, ~300 GB | ~$25 |
| ~5 M HTTPS requests | ~$5 |
| CloudFront Functions, ~5 M invocations | ~$0.50 |
| Invalidations, 200 paths | $0 (free tier) |
| S3 storage and GETs | <$1 |
| Route 53 hosted zone | $0.50 |
| Access logs, ~2.5 GB to CloudWatch, 30 days | ~$1.50 |
| **Total** | **roughly $30-35 per month** |

The CloudFront free tier (1 TB transfer and 10 million requests a month at
the time of writing) would cover all of this example's CloudFront usage.
The estimate above ignores it on purpose, so it still holds once a real
site outgrows it.
