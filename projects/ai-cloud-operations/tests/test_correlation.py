from __future__ import annotations

import unittest
from datetime import timedelta

from helpers import EPOCH, alert, deploy

from aiops.correlation import CorrelationConfig, correlate
from aiops.models import Anomaly


def _anomaly(service="svc", start=EPOCH) -> Anomaly:
    return Anomaly(
        service=service, metric="error_rate", window_start=start, window_end=start + timedelta(minutes=5),
        observed_value=0.5, baseline_mean=0.02, baseline_stddev=0.01, z_score=10.0, sample_size=50,
    )


class CorrelateTests(unittest.TestCase):
    def test_deploy_within_window_matches(self):
        a = _anomaly()
        d = deploy("svc", EPOCH - timedelta(minutes=10))
        result = correlate([a], [d], [], CorrelationConfig(window_minutes=15))
        self.assertEqual(result[0].deploys, (d,))

    def test_deploy_outside_window_does_not_match(self):
        a = _anomaly()
        d = deploy("svc", EPOCH - timedelta(minutes=30))
        result = correlate([a], [d], [], CorrelationConfig(window_minutes=15))
        self.assertEqual(result[0].deploys, ())

    def test_different_service_does_not_match(self):
        a = _anomaly(service="checkout")
        d = deploy("payments", EPOCH)
        result = correlate([a], [d], [], CorrelationConfig(window_minutes=15))
        self.assertEqual(result[0].deploys, ())

    def test_alert_after_window_end_matches(self):
        a = _anomaly()
        al = alert("svc", a.window_end + timedelta(minutes=3))
        result = correlate([a], [], [al], CorrelationConfig(window_minutes=15))
        self.assertEqual(result[0].alerts, (al,))

    def test_multiple_matches_sorted_by_time(self):
        a = _anomaly()
        d1 = deploy("svc", EPOCH - timedelta(minutes=5), version="v2")
        d2 = deploy("svc", EPOCH - timedelta(minutes=10), version="v1")
        result = correlate([a], [d1, d2], [], CorrelationConfig(window_minutes=15))
        self.assertEqual([d.version for d in result[0].deploys], ["v1", "v2"])

    def test_has_deploy_and_has_alert_properties(self):
        a = _anomaly()
        result = correlate([a], [], [], CorrelationConfig())
        self.assertFalse(result[0].has_deploy)
        self.assertFalse(result[0].has_alert)


if __name__ == "__main__":
    unittest.main()
