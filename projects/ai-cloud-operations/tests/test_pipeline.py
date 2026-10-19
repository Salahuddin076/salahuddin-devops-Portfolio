from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from helpers import EPOCH, deploy, make_logs

from aiops.audit import AuditLog
from aiops.pipeline import PipelineConfig, run


class PipelineTests(unittest.TestCase):
    def test_no_anomalies_means_no_proposals(self):
        logs = make_logs("svc", EPOCH, 5, [0.02] * 20)
        result = run(logs, [], [])
        self.assertEqual(result.items, ())
        self.assertEqual(result.proposals, ())

    def test_anomaly_produces_summary_and_proposal(self):
        logs = make_logs("svc", EPOCH, 5, [0.02] * 12 + [0.5])
        # Anomaly bucket 12 starts 60 minutes after EPOCH; put the deploy just
        # before it so it falls inside the default 15-minute correlation window.
        deploys = [deploy("svc", EPOCH + timedelta(minutes=55))]
        result = run(logs, deploys, [])
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.summary.source, "template")
        self.assertEqual(item.proposal.action, "rollback-deploy")

    def test_run_writes_to_audit_log_when_given_one(self):
        logs = make_logs("svc", EPOCH, 5, [0.02] * 12 + [0.5])
        with tempfile.TemporaryDirectory() as d:
            audit_log = AuditLog(Path(d) / "audit.jsonl")
            run(logs, [deploy("svc", EPOCH)], [], audit_log=audit_log)
            entries = audit_log.read_all()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["event"], "proposed")

    def test_run_without_audit_log_writes_nothing(self):
        logs = make_logs("svc", EPOCH, 5, [0.02] * 12 + [0.5])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "audit.jsonl"
            run(logs, [deploy("svc", EPOCH)], [], audit_log=None)
            self.assertFalse(path.exists())

    def test_custom_config_is_honoured(self):
        # 100 events/bucket so a 0.02 rate is an exact 2 errors (no rounding
        # noise): baseline is flat at 0.02, the last bucket bumps to 0.03.
        # stddev floor is 0.01, so z ~= 1.0: below the default threshold
        # (3.0), at or above a loosened one (0.9).
        logs = make_logs("svc", EPOCH, 5, [0.02] * 12 + [0.03], events_per_bucket=100)
        default_result = run(logs, [], [])
        self.assertEqual(default_result.items, ())  # z~=1.0 is below the default threshold of 3.0
        from dataclasses import replace
        from aiops.anomaly import AnomalyConfig
        loose_config = replace(PipelineConfig(), anomaly=AnomalyConfig(z_threshold=0.9))
        loose_result = run(logs, [], [], config=loose_config)
        self.assertEqual(len(loose_result.items), 1)
        self.assertAlmostEqual(loose_result.items[0].correlation.anomaly.z_score, 1.0)


if __name__ == "__main__":
    unittest.main()
