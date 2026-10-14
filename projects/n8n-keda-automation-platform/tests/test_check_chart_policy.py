"""check_chart_policy on the good and bad fixtures and on single-rule cases."""

from __future__ import annotations

import unittest

from helpers import FIXTURES

import check_chart_policy as cp

GOOD = (FIXTURES / "manifests" / "good.yaml").read_text()
BAD = (FIXTURES / "manifests" / "bad.yaml").read_text()


def rules(text, **kw):
    return sorted(f.rule for f in cp.check_text(text, "t", **kw))


def worker(grace=650, shutdown="630", timeout="600", pre=5, annotation=None, key=True):
    ann = f"\n  annotations:\n    n8n.example.com/max-execution-seconds: \"{annotation}\"" if annotation else ""
    key_env = '            - name: N8N_ENCRYPTION_KEY_FILE\n              value: "/mnt/secrets/k"\n' if key else ""
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: w{ann}
spec:
  template:
    spec:
      terminationGracePeriodSeconds: {grace}
      containers:
        - name: n8n
          image: n8nio/n8n:2.41.3
          args: ["worker"]
          lifecycle:
            preStop:
              sleep:
                seconds: {pre}
          env:
            - name: EXECUTIONS_MODE
              value: "queue"
{key_env}            - name: EXECUTIONS_TIMEOUT
              value: "{timeout}"
            - name: N8N_GRACEFUL_SHUTDOWN_TIMEOUT
              value: "{shutdown}"
"""


def scaled(min_rc=0, cooldown=300, list_name="bull:jobs:wait"):
    return f"""apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: s
spec:
  scaleTargetRef:
    name: w
  minReplicaCount: {min_rc}
  cooldownPeriod: {cooldown}
  triggers:
    - type: redis
      metadata:
        listName: "{list_name}"
"""


class FixtureTests(unittest.TestCase):
    def test_good_fixture_is_clean(self):
        self.assertEqual(cp.check_text(GOOD, "good"), [])

    def test_bad_fixture_hits_every_rule(self):
        found = rules(BAD)
        self.assertEqual(sorted(set(found)), [f"CP{n:03d}" for n in range(1, 11)])
        self.assertEqual(found.count("CP006"), 2)
        self.assertEqual(len(found), 11)

    def test_findings_never_contain_a_full_secret_value(self):
        for f in cp.check_text(BAD, "bad"):
            for literal in ("synthetic-literal-encryption-key", "synthetic-db-password", "synthetic-pass"):
                self.assertNotIn(literal, f.message)


class WorkerShutdownTests(unittest.TestCase):
    def test_compliant_worker(self):
        self.assertEqual(rules(worker()), [])

    def test_grace_below_max_execution(self):
        self.assertIn("CP001", rules(worker(grace=300)))

    def test_grace_must_cover_prestop_plus_shutdown(self):
        self.assertEqual(rules(worker(grace=630, shutdown="630", pre=5)), ["CP002"])

    def test_shutdown_timeout_below_max_execution(self):
        self.assertEqual(rules(worker(grace=700, shutdown="300")), ["CP002"])

    def test_flag_and_annotation_override_env(self):
        self.assertIn("CP001", rules(worker(), max_execution_seconds=900))
        self.assertIn("CP001", rules(worker(annotation="900")))

    def test_missing_max_execution_is_an_error(self):
        text = worker().replace('            - name: EXECUTIONS_TIMEOUT\n              value: "600"\n', "")
        self.assertIn("CP001", rules(text))


class ScaledObjectTests(unittest.TestCase):
    def test_zero_min_needs_cooldown(self):
        self.assertEqual(rules(scaled(cooldown=60)), ["CP005"])
        self.assertEqual(rules(scaled(cooldown=60), min_cooldown=30), [])
        self.assertEqual(rules(scaled(min_rc=1, cooldown=60)), [], "cooldown only matters when scaling to zero")

    def test_defaults_follow_keda(self):
        text = scaled().replace("  minReplicaCount: 0\n", "").replace("  cooldownPeriod: 300\n", "")
        self.assertEqual(rules(text), [], "KEDA defaults: min 0, cooldown 300")

    def test_list_key_must_be_a_bull_list(self):
        self.assertEqual(rules(scaled(list_name="jobs:wait")), ["CP009"])
        self.assertEqual(rules(scaled(list_name="bull:jobs:active")), [])
        self.assertEqual(rules(scaled(list_name="n8n:jobs:wait"), bull_prefix="n8n"), [])


class EnvTests(unittest.TestCase):
    def test_file_and_ref_forms_pass(self):
        self.assertEqual(rules(worker()), [])
        self.assertEqual(rules(GOOD), [])

    def test_boolean_flags_with_secretish_names_pass(self):
        text = worker().replace('              value: "queue"\n',
                                '              value: "queue"\n            - name: N8N_BASIC_AUTH_ACTIVE\n'
                                '              value: "false"\n', 1)
        self.assertEqual(rules(text), [])

    def test_missing_key_on_n8n_container(self):
        self.assertEqual(rules(worker(key=False)), ["CP008"])


if __name__ == "__main__":
    unittest.main()
