"""Duplicate-processing guard: a job replayed after failover is skipped."""

import unittest
from datetime import timedelta

import helpers  # noqa: F401  (sets sys.path)
from helpers import DR, PRIMARY, Clock

from worker_idempotency import (
    FencedRegion,
    InMemoryStore,
    MissingIdempotencyKey,
    Worker,
)

JOB = {"id": "job-1", "idempotency_key": "order-1001:capture-payment", "order_id": 1001}


class Handler:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, job):
        self.calls.append(job["idempotency_key"])
        if self.fail:
            raise RuntimeError("payment provider timeout")
        return f"payment-{job['order_id']}"


class WorkerIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.table = InMemoryStore()  # the replicated processed_jobs table

    def worker(self, region, epoch, active=True, store=None):
        return Worker(store or self.table, region, epoch, lambda: active, clock=self.clock)

    def test_replayed_job_is_skipped_after_failover(self):
        handler = Handler()
        before = self.worker(PRIMARY, epoch=0).process(JOB, handler)
        self.assertEqual(before.action, "processed")

        # Failover: us-west-2 is promoted (epoch 1) and the queue redelivers
        # the job, or an operator replays the last hour to be safe.
        after = self.worker(DR, epoch=1).process(JOB, handler)
        self.assertEqual(after.action, "skipped-duplicate")
        self.assertEqual(handler.calls, [JOB["idempotency_key"]])  # side effect ran once

    def test_redelivery_in_same_region_is_skipped(self):
        handler = Handler()
        w = self.worker(PRIMARY, 0)
        w.process(JOB, handler)
        self.assertEqual(w.process(JOB, handler).action, "skipped-duplicate")
        self.assertEqual(len(handler.calls), 1)

    def test_live_lease_blocks_second_worker(self):
        # The old primary claimed the job, then the region died mid-job.
        self.table.claim(JOB["idempotency_key"], PRIMARY, 0, self.clock(), timedelta(minutes=5))
        handler = Handler()
        out = self.worker(DR, 1).process(JOB, handler)
        self.assertEqual(out.action, "skipped-in-progress")
        self.assertEqual(handler.calls, [])

    def test_expired_lease_is_taken_over_and_stale_completion_discarded(self):
        key = JOB["idempotency_key"]
        self.table.claim(key, PRIMARY, 0, self.clock(), timedelta(minutes=5))
        self.clock.now += timedelta(minutes=6)  # lease expired
        handler = Handler()
        out = self.worker(DR, 1).process(JOB, handler)
        self.assertEqual(out.action, "processed")
        # The old worker wakes up and tries to record its result: rejected.
        self.assertFalse(self.table.complete(key, 0, "late-result", self.clock()))
        self.assertEqual(self.table.rows[key].result_ref, "payment-1001")
        self.assertEqual(self.table.rows[key].region, DR)

    def test_failed_handler_releases_claim_for_retry(self):
        with self.assertRaises(RuntimeError):
            self.worker(DR, 1).process(JOB, Handler(fail=True))
        self.assertNotIn(JOB["idempotency_key"], self.table.rows)
        self.assertEqual(self.worker(DR, 1).process(JOB, Handler()).action, "processed")

    def test_fenced_region_refuses_to_process(self):
        handler = Handler()
        with self.assertRaises(FencedRegion):
            self.worker(PRIMARY, 0, active=False).process(JOB, handler)
        self.assertEqual(handler.calls, [])
        self.assertEqual(self.table.rows, {})

    def test_job_without_key_is_rejected(self):
        with self.assertRaises(MissingIdempotencyKey):
            self.worker(PRIMARY, 0).process({"id": "job-2"}, Handler())

    def test_unreplicated_claim_is_reprocessed_documented_rpo_gap(self):
        # Snapshot of the table as the DR replica last saw it, then the old
        # primary finishes a job whose rows never replicate (unplanned loss).
        dr_replica = self.table.copy()
        handler = Handler()
        self.worker(PRIMARY, 0).process(JOB, handler)
        out = self.worker(DR, 1, store=dr_replica).process(JOB, handler)
        # Runs twice: why downstream calls must carry the same idempotency key.
        self.assertEqual(out.action, "processed")
        self.assertEqual(len(handler.calls), 2)


if __name__ == "__main__":
    unittest.main()
