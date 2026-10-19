from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aiops import generator
from aiops.anomaly import AnomalyConfig, detect
from aiops.correlation import correlate
from aiops.io import read_alerts, read_deploys, read_logs
from aiops.remediation import propose


class GeneratorTests(unittest.TestCase):
    def test_same_seed_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            generator.generate(a, seed=11)
            generator.generate(b, seed=11)
            for name in ("logs.jsonl", "deploys.jsonl", "alerts.jsonl"):
                self.assertEqual((Path(a) / name).read_bytes(), (Path(b) / name).read_bytes())

    def test_different_seed_changes_log_content(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            generator.generate(a, seed=11)
            generator.generate(b, seed=99)
            self.assertNotEqual((Path(a) / "logs.jsonl").read_bytes(), (Path(b) / "logs.jsonl").read_bytes())

    def test_sample_data_produces_exactly_one_anomaly_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            generator.generate(d, seed=11)
            logs = read_logs(Path(d) / "logs.jsonl")
            deploys = read_deploys(Path(d) / "deploys.jsonl")
            alerts = read_alerts(Path(d) / "alerts.jsonl")
            anomalies = detect(logs, AnomalyConfig())
            self.assertEqual(len(anomalies), 1)
            self.assertEqual(anomalies[0].service, generator.ANOMALY_SERVICE)
            correlations = correlate(anomalies, deploys, alerts)
            self.assertTrue(correlations[0].has_deploy)
            self.assertTrue(correlations[0].has_alert)
            proposal = propose(correlations[0])
            self.assertEqual(proposal.action, "rollback-deploy")
            self.assertTrue(proposal.allowed)


if __name__ == "__main__":
    unittest.main()
