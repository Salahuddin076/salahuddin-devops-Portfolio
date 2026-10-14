import unittest

from helpers import FakeClock

from adapters import COMPLETED, IN_PROGRESS, InMemoryStore
from idempotency import IdempotencyGuard, Outcome, payload_hash


class IdempotencyGuardTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.store = InMemoryStore()
        self.guard = IdempotencyGuard(self.store, ttl_seconds=3600, lock_seconds=60, clock=self.clock)

    def test_first_seen_writes_in_progress_record_with_ttl(self):
        claim = self.guard.claim("key-1", "hash-a")
        self.assertIs(claim.outcome, Outcome.FIRST_SEEN)
        record = self.store.items["IDEMPOTENCY#key-1"]
        self.assertEqual(record["status"], IN_PROGRESS)
        self.assertEqual(record["expires_at"], int(self.clock.now) + 3600)
        self.assertEqual(record["lock_expires_at"], int(self.clock.now) + 60)

    def test_duplicate_while_in_progress(self):
        self.guard.claim("key-1", "hash-a")
        self.assertIs(self.guard.claim("key-1", "hash-a").outcome, Outcome.DUPLICATE_IN_PROGRESS)

    def test_duplicate_completed_returns_stored_result(self):
        self.guard.claim("key-1", "hash-a")
        self.guard.complete("key-1", {"orderId": "ord_1", "totalCents": 3900})
        self.assertEqual(self.store.items["IDEMPOTENCY#key-1"]["status"], COMPLETED)

        claim = self.guard.claim("key-1", "hash-a")
        self.assertIs(claim.outcome, Outcome.DUPLICATE_COMPLETED)
        self.assertEqual(claim.stored_result, {"orderId": "ord_1", "totalCents": 3900})

    def test_key_reused_with_different_payload(self):
        self.guard.claim("key-1", "hash-a")
        self.guard.complete("key-1", {"orderId": "ord_1"})
        self.assertIs(self.guard.claim("key-1", "hash-b").outcome, Outcome.PAYLOAD_MISMATCH)

    def test_stale_lock_can_be_taken_over(self):
        self.guard.claim("key-1", "hash-a")
        self.clock.advance(61)
        self.assertIs(self.guard.claim("key-1", "hash-a").outcome, Outcome.FIRST_SEEN)

    def test_completed_record_is_not_taken_over_when_lock_expires(self):
        self.guard.claim("key-1", "hash-a")
        self.guard.complete("key-1", {"orderId": "ord_1"})
        self.clock.advance(120)
        self.assertIs(self.guard.claim("key-1", "hash-a").outcome, Outcome.DUPLICATE_COMPLETED)

    def test_expired_record_counts_as_new_even_before_ttl_deletion(self):
        self.guard.claim("key-1", "hash-a")
        self.guard.complete("key-1", {"orderId": "ord_1"})
        self.clock.advance(3601)
        # Item is still physically present (TTL deletion is lazy) ...
        self.assertIn("IDEMPOTENCY#key-1", self.store.items)
        # ... but the condition treats it as gone.
        self.assertIs(self.guard.claim("key-1", "hash-a").outcome, Outcome.FIRST_SEEN)

    def test_release_allows_immediate_retry(self):
        self.guard.claim("key-1", "hash-a")
        self.guard.release("key-1")
        self.assertIs(self.guard.claim("key-1", "hash-a").outcome, Outcome.FIRST_SEEN)

    def test_one_conditional_write_per_claim(self):
        self.guard.claim("key-1", "hash-a")
        self.guard.claim("key-1", "hash-a")
        self.assertEqual(self.store.conditional_put_calls, 2)

    def test_ttl_must_exceed_lock(self):
        with self.assertRaises(ValueError):
            IdempotencyGuard(self.store, ttl_seconds=60, lock_seconds=60)

    def test_payload_hash_ignores_key_order(self):
        self.assertEqual(payload_hash({"a": 1, "b": [1, 2]}), payload_hash({"b": [1, 2], "a": 1}))
        self.assertNotEqual(payload_hash({"a": 1}), payload_hash({"a": 2}))


if __name__ == "__main__":
    unittest.main()
