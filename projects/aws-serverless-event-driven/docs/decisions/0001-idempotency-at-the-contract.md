# ADR 0001: Idempotency is part of the API contract

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-serverless-event-driven (portfolio implementation)

## Context

Duplicates reach this pipeline from three places:

1. **Clients retry.** A mobile client on a bad network, or a server-side
   caller after a timeout, sends the same order again without knowing
   whether the first attempt landed.
2. **SQS standard queues deliver at least once.** A message can arrive twice
   even when it was sent once.
3. **Our own retries.** A batch item that failed after doing part of its work
   (order recorded, event not published) is redelivered.

Creating an order twice charges or ships twice. "Usually doesn't happen"
isn't good enough for a write that moves money.

## Decision

1. **`Idempotency-Key` is a required header on `POST /orders`.** A missing or
   malformed key is a `400`, the same as a schema error. The key names the
   client's *intent* ("this order"), so the client generates it once per
   order and reuses it on every retry.
2. **The order ID is derived from the key** (`ord_` + SHA-256 prefix). A retry
   gets the same `orderId` in its `202` without any lookup on the
   synchronous path.
3. **Deduplication happens once, in the processor**, with one conditional
   `PutItem` on `IDEMPOTENCY#<key>`. That single mechanism covers all three
   duplicate sources above. The record moves `IN_PROGRESS` → `COMPLETED` and
   stores the result, which is returned (logged, and available to a future status
   endpoint) for later duplicates.
4. **A payload hash is stored with the key.** The same key with a different
   body is a client bug and is rejected as poison rather than silently
   answered with the first order's result.
5. **Records expire through TTL** (24 hours by default). The condition also
   treats `expires_at < now` as absent, because TTL deletion is lazy.
6. **The in-progress lock expires** after the processor timeout plus 5
   seconds, so a crash mid-record can't block a key until the TTL runs out.

## Alternatives considered

- **Server-generated dedup (hash of the body).** Two genuinely identical
  orders, such as the same customer buying the same item twice on purpose,
  would collapse into one. Only the client knows whether a request is a retry.
- **SQS FIFO with `MessageDeduplicationId`.** Covers only a five-minute
  window and only duplicates entering the queue, not the processor's own
  partial failures. It also brings FIFO throughput limits and ordering
  semantics nobody needs here.
- **Deduplicating in ingest too** (a conditional write before enqueuing).
  It would turn a client retry into a cheap no-op, but it adds a DynamoDB
  write and IAM permission to the latency-sensitive path, and the processor
  would still need its own check for SQS redelivery. One mechanism is easier
  to reason about. Ingest could be added later as an optimisation without
  changing the contract.
- **Make the effects naturally idempotent** (upsert the order, let event
  consumers dedupe). The order upsert is naturally idempotent, and consumers
  *do* get a deterministic event ID. But "publish exactly one event per
  order in the normal case" is far easier for every consumer, and the claim
  record is what makes that cheap.

## Consequences

- Clients must generate and persist a key per order. It's a small burden,
  and it's the same pattern as the major payment APIs, so client developers
  will recognise it.
- Event publication is at least once, not exactly once: a crash between
  `PutEvents` and marking the claim complete republishes. Consumers dedupe on
  the event `id` (UUIDv5 of the order ID).
- A duplicate arriving while the first delivery is still running is retried
  after the visibility timeout. It counts toward `maxReceiveCount`, which is
  one reason the default is 5, not 3.
- Keys are global, not per client, because there is no authentication yet.
  With an authorizer, the record key becomes `<clientId>#<key>` (see
  [security](../security.md#gaps-on-purpose-for-a-portfolio-stack)).
- After the TTL window, the same key is treated as new. 24 hours comfortably
  exceeds any sane client retry policy, and it is configurable
  (`idempotency_ttl_hours`).
