# ADR 0002: A CloudFront Function, not Lambda@Edge, for URI rewriting

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** cloudfront-s3-static-delivery (portfolio implementation)

## Context

With OAC on the S3 REST endpoint ([ADR 0001](0001-oac-over-oai.md)), S3
doesn't resolve directory indexes: `/docs/` asks for a key named `docs/`,
which doesn't exist. `default_root_object` only covers `/`. Something at
the edge has to turn `/docs/` into `/docs/index.html`, and should redirect
`/docs` to `/docs/` so relative links in the page resolve against the
right base.

There are two edge compute options:

| | CloudFront Functions | Lambda@Edge |
|---|---|---|
| Runs at | All edge locations, viewer events only | Regional edge caches, viewer and origin events |
| Startup / limit | Sub-millisecond, 10 KB code, about 1 ms compute | Up to 5 s (viewer) or 30 s (origin), 1-50 MB |
| Capabilities | Request/response rewriting, headers, redirects, KeyValueStore | Network calls, body access, any Node.js or Python package |
| Price (approx.) | ~$0.10 per million | ~$0.60 per million + duration |
| Deploy | Seconds, in place | Versioned function in us-east-1, replicated, slow to delete |
| Local testing | None (restricted JS runtime) | Normal Node.js/Python tooling |

## Decision

Use a CloudFront Function (`cloudfront-js-2.0`) on the viewer-request
event:

1. URI ends with `/` → rewrite to `index.html`.
2. The last segment contains a `.` → it's a file, pass it through.
3. Otherwise → 301 to the URI with `/` appended, keeping the query string.

The URI is matched as delivered (percent-encoded) and never decoded.

Because the runtime can't be run locally, the behaviour is specified in
Python (`scripts/rewrite.py`) with unit tests. The JS is reviewed against it
and checked in two ways: a regex test that both have the same branches, and,
where node is available (always in CI), executing the JS handler on the same
events and requiring identical output.

## Consequences

- Six times cheaper per request than Lambda@Edge, with no cold starts and no
  regional replication to clean up. The rewrite happens before the cache
  lookup, so `/docs/` and `/docs/index.html` share one cache entry.
- Two implementations must be kept in step. The parity tests catch a branch
  or literal changed on one side only. They can't catch CloudFront
  rejecting a syntax feature node accepts, so the function sticks to
  documented features (`var`, `for...in`, `endsWith`). A
  `aws cloudfront test-function` run in a real account would close that gap.
- Repeated query keys come out grouped (`?tag=a&x=1&tag=b` becomes
  `?tag=a&tag=b&x=1`), because CloudFront presents the query as an object.
  The meaning is the same, but the order differs. JavaScript also orders
  integer-like keys first. Neither matters for a static site.
- Anything that needs a network call (auth against an IdP, A/B
  assignment from a service) would need Lambda@Edge. That's a separate
  function on a separate event, not a reason to move this one.
