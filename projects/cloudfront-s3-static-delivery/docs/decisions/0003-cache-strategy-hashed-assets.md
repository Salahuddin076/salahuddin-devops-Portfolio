# ADR 0003: Content-hashed assets are immutable, HTML always revalidates

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** cloudfront-s3-static-delivery (portfolio implementation)

## Context

A static site wants two contradictory things: assets cached as long as
possible, for speed and cost, and changes visible right after a deploy.
Long TTLs on everything mean stale pages. Short TTLs on everything mean
every view revalidates every file. Invalidating `/*` on every deploy
throws away the whole edge cache, cost aside.

## Decision

Split by how the URL relates to the content. `scripts/deploy_plan.py`
sets the header on upload:

| Files | `Cache-Control` | Why |
|---|---|---|
| Content-hashed JS/CSS: `name.<8+ hex>.js` / `.css` | `public, max-age=31536000, immutable` | The URL changes when the content does, so a cached copy is never wrong. `immutable` stops browsers revalidating on reload |
| HTML | `no-cache` | Must reflect the latest deploy. Browsers revalidate every time, and the ETag makes that a cheap 304 |
| Everything else (images, `robots.txt`, unhashed CSS) | `public, max-age=300` | Unversioned URLs: staleness is bounded to five minutes |

Deploy rules that follow:

- **Upload order:** hashed assets, then other files, then HTML, then
  deletions. New HTML never references an asset that isn't there yet.
- **Invalidate** changed or deleted non-hashed objects, with `/dir/` next
  to `/dir/index.html`. **Never invalidate hashed assets.** New paths are
  skipped (a cached 404 for them expires after the 10-second error TTL).
  Above a threshold (default 15 paths), collapse to `/*`. The pricing
  trade-off is in [cost](../cost.md#invalidation-per-path-vs-wildcard).
- **Keep superseded hashed assets for one release** (`--keep-old-hashed`)
  so pages loaded before the deploy can still fetch their bundles.

The distribution uses the managed `CachingOptimized` policy (min 1 s,
default 1 day, max 1 year; no query strings, headers or cookies in the
key). The object's `Cache-Control` sets the TTL within those bounds.

## Consequences

- Repeat visitors fetch only HTML (usually a 304) and new assets. The edge
  cache survives deploys.
- **HTML at the edge:** with `no-cache` from the origin and a 1-second
  minimum TTL in the policy, CloudFront revalidates HTML with S3 roughly
  every second per edge. The HTML invalidation is then mostly a safety net,
  but a real one: it fixes HTML that was uploaded without the header (it
  would otherwise get the policy's one-day default), and the five-minute
  files genuinely need it. A custom cache policy with `s-maxage` on HTML
  would cut origin requests further, at the cost of relying on invalidation
  for every HTML change.
- The build must content-hash assets (every mainstream bundler does). An
  unhashed `styles.css`, like the demo site's, falls into the five-minute
  class. That's correct, just slower to propagate.
- The hash pattern is a convention (`.<8+ lowercase hex>.`). A bundler
  that uses base64 or uppercase hashes needs the regex changed.
- `deploy_plan.py` compares local MD5s with S3 ETags. Multipart uploads and
  SSE-KMS objects don't have MD5 ETags and are re-uploaded every time.
  That's correct, just not minimal.
