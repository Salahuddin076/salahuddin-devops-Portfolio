from __future__ import annotations

import unittest
from datetime import timedelta

from helpers import EPOCH, alert, deploy

from aiops.correlation import correlate
from aiops.models import Anomaly
from aiops.remediation import ALLOWED_ACTIONS, RemediationConfig, propose


def _anomaly(z=10.0):
    return Anomaly(
        service="checkout-api", metric="error_rate", window_start=EPOCH,
        window_end=EPOCH + timedelta(minutes=5), observed_value=0.4, baseline_mean=0.02,
        baseline_stddev=0.01, z_score=z, sample_size=50,
    )


class ProposeTests(unittest.TestCase):
    def test_deploy_correlation_proposes_rollback(self):
        c = correlate([_anomaly()], [deploy("checkout-api", EPOCH - timedelta(minutes=2))], [])[0]
        proposal = propose(c)
        self.assertEqual(proposal.action, "rollback-deploy")
        self.assertTrue(proposal.allowed)

    def test_alert_only_correlation_proposes_scale_up(self):
        c = correlate([_anomaly()], [], [alert("checkout-api", EPOCH + timedelta(minutes=6))])[0]
        proposal = propose(c)
        self.assertEqual(proposal.action, "scale-up")
        self.assertTrue(proposal.allowed)

    def test_isolated_moderate_anomaly_proposes_restart(self):
        c = correlate([_anomaly(z=4.0)], [], [])[0]
        proposal = propose(c)
        self.assertEqual(proposal.action, "restart-pod")
        self.assertTrue(proposal.allowed)

    def test_isolated_severe_anomaly_escalates(self):
        c = correlate([_anomaly(z=9.0)], [], [])[0]
        proposal = propose(c)
        self.assertEqual(proposal.action, "escalate")
        self.assertTrue(proposal.allowed)

    def test_every_proposed_action_is_on_the_allow_list(self):
        for z in (0.0, 3.5, 4.9, 5.0, 20.0):
            c = correlate([_anomaly(z=z)], [], [])[0]
            proposal = propose(c)
            self.assertIn(proposal.action, ALLOWED_ACTIONS)

    def test_proposal_id_is_deterministic_for_the_same_anomaly(self):
        c = correlate([_anomaly()], [deploy("checkout-api", EPOCH)], [])[0]
        p1 = propose(c)
        p2 = propose(c)
        self.assertEqual(p1.id, p2.id)

    def test_proposal_id_differs_for_different_services(self):
        c1 = correlate([_anomaly()], [deploy("checkout-api", EPOCH)], [])[0]
        c2 = correlate([Anomaly(service="payments-api", metric="error_rate", window_start=EPOCH,
                                 window_end=EPOCH + timedelta(minutes=5), observed_value=0.4,
                                 baseline_mean=0.02, baseline_stddev=0.01, z_score=10.0, sample_size=50)],
                        [deploy("payments-api", EPOCH)], [])[0]
        self.assertNotEqual(propose(c1).id, propose(c2).id)

    def test_custom_scale_up_threshold(self):
        c = correlate([_anomaly()], [], [alert("checkout-api", EPOCH + timedelta(minutes=6))])[0]
        proposal = propose(c, RemediationConfig(scale_up_alert_threshold=2))
        self.assertNotEqual(proposal.action, "scale-up")


if __name__ == "__main__":
    unittest.main()
