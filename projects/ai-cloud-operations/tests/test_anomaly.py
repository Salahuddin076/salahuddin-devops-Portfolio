from __future__ import annotations

import unittest

from helpers import EPOCH, make_logs

from aiops.anomaly import AnomalyConfig, detect


class DetectTests(unittest.TestCase):
    def test_flat_baseline_no_anomaly(self):
        rates = [0.02] * 20
        events = make_logs("svc", EPOCH, 5, rates)
        anomalies = detect(events, AnomalyConfig(baseline_windows=12))
        self.assertEqual(anomalies, [])

    def test_spike_after_flat_baseline_is_detected(self):
        rates = [0.02] * 12 + [0.5]
        events = make_logs("svc", EPOCH, 5, rates)
        anomalies = detect(events, AnomalyConfig(baseline_windows=12, z_threshold=3.0))
        self.assertEqual(len(anomalies), 1)
        a = anomalies[0]
        self.assertEqual(a.service, "svc")
        self.assertAlmostEqual(a.observed_value, 0.5)
        self.assertGreaterEqual(a.z_score, 3.0)

    def test_small_bucket_below_min_events_is_ignored(self):
        rates = [0.02] * 12 + [0.9]
        events = make_logs("svc", EPOCH, 5, rates, events_per_bucket=3)
        anomalies = detect(events, AnomalyConfig(baseline_windows=12, min_events=5))
        self.assertEqual(anomalies, [])

    def test_not_enough_history_is_not_scored(self):
        rates = [0.02] * 5 + [0.9]  # fewer than baseline_windows of history
        events = make_logs("svc", EPOCH, 5, rates)
        anomalies = detect(events, AnomalyConfig(baseline_windows=12))
        self.assertEqual(anomalies, [])

    def test_zero_variance_baseline_uses_stddev_floor(self):
        # Perfectly flat baseline (stddev == 0) followed by a small bump: should
        # not explode to infinity, and should still cross a low threshold.
        rates = [0.0] * 12 + [0.1]
        events = make_logs("svc", EPOCH, 5, rates, events_per_bucket=50)
        anomalies = detect(events, AnomalyConfig(baseline_windows=12, z_threshold=3.0, min_stddev=0.01))
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0].baseline_stddev, 0.01)

    def test_multiple_services_scored_independently(self):
        events = (
            make_logs("a", EPOCH, 5, [0.02] * 12 + [0.5])
            + make_logs("b", EPOCH, 5, [0.02] * 13)
        )
        anomalies = detect(events, AnomalyConfig(baseline_windows=12))
        services = {a.service for a in anomalies}
        self.assertEqual(services, {"a"})

    def test_results_sorted_by_window_then_service(self):
        events = (
            make_logs("b", EPOCH, 5, [0.02] * 12 + [0.5])
            + make_logs("a", EPOCH, 5, [0.02] * 12 + [0.5])
        )
        anomalies = detect(events, AnomalyConfig(baseline_windows=12))
        self.assertEqual([a.service for a in anomalies], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
