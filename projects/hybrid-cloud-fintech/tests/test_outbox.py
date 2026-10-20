"""Unit tests for InMemoryOutbox and FileOutbox: append, pending, mark_done,
mark_attempt_failed, and that both backends behave identically."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import CountingIds, FakeClock

from degrade.outbox import FileOutbox, InMemoryOutbox, OutboxStatus


def make_backends(tmpdir: str):
    clock = FakeClock()
    mem = InMemoryOutbox(clock=clock, id_factory=CountingIds("mem"))
    file_outbox = FileOutbox(Path(tmpdir) / "outbox.json", clock=clock, id_factory=CountingIds("file"))
    return clock, {"memory": mem, "file": file_outbox}


class OutboxBehaviorTests(unittest.TestCase):
    """Runs the same assertions against both backends, parameterized by name."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.clock, self.backends = make_backends(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_creates_pending_entry(self) -> None:
        for name, outbox in self.backends.items():
            with self.subTest(backend=name):
                entry = outbox.append("post_ledger_entry", {"account": "acct-1"})
                self.assertEqual(entry.status, OutboxStatus.PENDING)
                self.assertEqual(entry.attempts, 0)
                pending = outbox.pending()
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0].id, entry.id)
                self.assertEqual(pending[0].payload, {"account": "acct-1"})

    def test_mark_done_removes_from_pending(self) -> None:
        for name, outbox in self.backends.items():
            with self.subTest(backend=name):
                entry = outbox.append("post_ledger_entry", {"account": "acct-1"})
                outbox.mark_done(entry.id)
                self.assertEqual(outbox.pending(), [])
                stored = outbox.get(entry.id)
                self.assertEqual(stored.status, OutboxStatus.DONE)
                self.assertIsNotNone(stored.completed_at)

    def test_mark_attempt_failed_increments_and_stays_pending_under_budget(self) -> None:
        for name, outbox in self.backends.items():
            with self.subTest(backend=name):
                entry = outbox.append("post_ledger_entry", {"account": "acct-1"})
                updated = outbox.mark_attempt_failed(entry.id, "timeout", max_attempts=3)
                self.assertEqual(updated.attempts, 1)
                self.assertEqual(updated.status, OutboxStatus.PENDING)
                self.assertEqual(len(outbox.pending()), 1)

    def test_mark_attempt_failed_moves_to_failed_at_budget(self) -> None:
        for name, outbox in self.backends.items():
            with self.subTest(backend=name):
                entry = outbox.append("post_ledger_entry", {"account": "acct-1"})
                for _ in range(3):
                    updated = outbox.mark_attempt_failed(entry.id, "timeout", max_attempts=3)
                self.assertEqual(updated.status, OutboxStatus.FAILED)
                self.assertEqual(outbox.pending(), [])
                self.assertEqual(len(outbox.all()), 1)

    def test_multiple_entries_independent(self) -> None:
        for name, outbox in self.backends.items():
            with self.subTest(backend=name):
                a = outbox.append("op_a", {"x": 1})
                b = outbox.append("op_b", {"x": 2})
                outbox.mark_done(a.id)
                self.assertEqual([e.id for e in outbox.pending()], [b.id])


class FileOutboxPersistenceTests(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outbox.json"
            outbox1 = FileOutbox(path, id_factory=CountingIds("f"))
            entry = outbox1.append("post_ledger_entry", {"account": "acct-9"})

            outbox2 = FileOutbox(path)
            pending = outbox2.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].id, entry.id)
            self.assertEqual(pending[0].payload, {"account": "acct-9"})

    def test_file_is_human_readable_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outbox.json"
            outbox = FileOutbox(path, id_factory=CountingIds("f"))
            outbox.append("post_ledger_entry", {"account": "acct-9"})
            raw = path.read_text()
            self.assertIn('"operation": "post_ledger_entry"', raw)
            self.assertIn('"account": "acct-9"', raw)


if __name__ == "__main__":
    unittest.main()
