from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from helpers import EPOCH, deploy

from aiops.audit import AuditLog, RemediationNotAllowed
from aiops.correlation import correlate
from aiops.models import Anomaly
from aiops.remediation import propose


def _proposal(allowed_override=None):
    a = Anomaly(service="checkout-api", metric="error_rate", window_start=EPOCH,
                window_end=EPOCH + timedelta(minutes=5), observed_value=0.4, baseline_mean=0.02,
                baseline_stddev=0.01, z_score=10.0, sample_size=50)
    c = correlate([a], [deploy("checkout-api", EPOCH)], [])[0]
    p = propose(c)
    if allowed_override is not None:
        p = dataclasses.replace(p, allowed=allowed_override)
    return p


class AuditLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "audit.jsonl"
        self.log = AuditLog(self.path)

    def test_record_proposal_appends_one_line(self):
        self.log.record_proposal(_proposal())
        entries = self.log.read_all()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["event"], "proposed")

    def test_approve_allowed_proposal_appends_entry(self):
        p = _proposal()
        self.log.record_proposal(p)
        self.log.approve(p, actor="oncall@example.com")
        entries = self.log.read_all()
        self.assertEqual([e["event"] for e in entries], ["proposed", "approved"])
        self.assertEqual(entries[1]["actor"], "oncall@example.com")

    def test_approve_disallowed_proposal_raises_and_does_not_write(self):
        p = _proposal(allowed_override=False)
        self.log.record_proposal(p)
        with self.assertRaises(RemediationNotAllowed):
            self.log.approve(p, actor="oncall@example.com")
        entries = self.log.read_all()
        self.assertEqual(len(entries), 1)  # only the "proposed" entry

    def test_reject_appends_with_reason(self):
        p = _proposal()
        self.log.reject(p, actor="oncall@example.com", reason="not the right call")
        entries = self.log.read_all()
        self.assertEqual(entries[0]["event"], "rejected")
        self.assertEqual(entries[0]["details"]["reason"], "not the right call")

    def test_log_is_append_only_across_instances(self):
        p = _proposal()
        AuditLog(self.path).record_proposal(p)
        AuditLog(self.path).approve(p, actor="a")
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            json.loads(line)  # each line is valid, standalone JSON

    def test_read_all_on_missing_file_returns_empty(self):
        missing = Path(self.tmp.name) / "missing.jsonl"
        self.assertEqual(AuditLog(missing).read_all(), [])


if __name__ == "__main__":
    unittest.main()
