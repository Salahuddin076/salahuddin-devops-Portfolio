# ADR 0003: Valkey is rebuildable: no global datastore

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-multi-region-eks-dr (reference implementation)

## Context

Each region runs an ElastiCache for Valkey replication group. The app uses
it for read-through caching of catalog and order lookups, rate-limit
counters, and short-lived sessions. ElastiCache Global Datastore can
replicate a replication group to a secondary region, and promoting that
secondary keeps the cache warm after a failover.

## Decision

Each region has an independent Valkey replication group (Multi-AZ inside
the region) with no Global Datastore and no snapshots
(`snapshot_retention_limit = 0`). After a failover, the DR cache starts
from whatever it cached while serving standby reads and fills up from
Aurora.

The application contract that makes this safe:

- **Aurora is the only source of truth.** Nothing is written only to the
  cache. Anything that must survive a failover goes to PostgreSQL first.
- **Sessions are allowed to drop.** A failover logs users out, or the API
  re-issues a session from a signed token. The client already has to
  handle that for an ordinary session expiry.
- **Rate limits restart.** For a few minutes after a failover the counters
  are empty. Limits are a protection, not an accounting record.

## Why not Global Datastore

- **It doesn't remove the hard problem.** The cache would be warm, but
  the data it holds could be up to the replication lag older than Aurora,
  and both lag independently. A warm cache full of entries that disagree
  with the promoted database is worse than a cold one, because staleness
  bugs are harder to spot than a slow first minute.
- **It adds a second promotion to the runbook.** That is one more step
  that can fail, one more thing to fence, and one more thing to fail back.
  Its failover is a separate API with its own ordering constraints.
- **Cost.** Global Datastore needs the same node type in the DR region (no
  downsizing the standby) and adds cross-region transfer for every write.
  With a cache that only takes reads in the standby, the DR region runs a
  single small node.
- **The cold-start cost is bounded and testable.** The game day measures
  the post-failover latency and Aurora load while the cache refills (see
  [runbooks/game-day.md](../../runbooks/game-day.md)), and the scale step
  raises API replicas first.

## Consequences

- The DR region's Valkey runs `cache_nodes = 1` (no in-region replica) to
  save cost. Losing that node during a DR period costs a cold cache, which
  the app is designed to tolerate.
- Aurora needs headroom for a cache-miss surge right after failover. The
  DR cluster's instance class is the same as the primary's by default
  (`aurora_instance_class`) and is not downsized.
- If a future feature needs cross-region cache state (for example,
  distributed locks that must survive failover), that state belongs in
  Aurora or in a store with explicit consistency semantics, not in a
  replicated cache.
