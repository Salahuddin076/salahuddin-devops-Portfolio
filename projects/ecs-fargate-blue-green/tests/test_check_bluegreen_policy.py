"""check_bluegreen_policy.py: real settings pass, each bad fixture fails with its rule."""

import copy
import json
import unittest

from helpers import CONFIG_DIR, FIXTURES

import check_bluegreen_policy as policy

EXPECTED = {
    "bad-alarm-rollback-missing.json": {"BG003"},
    "bad-missing-keys.json": {"BG000"},
    "bad-not-json.json": {"BG000"},
    "bad-open-test-listener.json": {"BG005"},
    "bad-prod-all-at-once.json": {"BG001"},
    "bad-prod-no-alarms.json": {"BG002"},
    "bad-rollback-off.json": {"BG003"},
    "bad-unknown-config.json": {"BG006", "BG007"},
    "bad-zero-termination.json": {"BG004"},
}


def load(env):
    return json.loads((CONFIG_DIR / f"{env}.json").read_text())


class RealSettingsTests(unittest.TestCase):
    def test_every_environment_passes(self):
        for path in sorted(CONFIG_DIR.glob("*.json")):
            with self.subTest(path=path.name):
                report = policy.check_file(path)
                self.assertTrue(report.ok, report.findings)

    def test_environment_shapes(self):
        dev, staging, prod = load("dev"), load("staging"), load("prod")
        self.assertEqual(dev["deployment_config_name"], "CodeDeployDefault.ECSAllAtOnce")
        self.assertEqual((dev["capacity"]["on_demand_weight"], dev["capacity"]["spot_weight"]), (0, 1))
        self.assertIn("Linear", staging["deployment_config_name"])
        self.assertIn("Canary", prod["deployment_config_name"])
        self.assertEqual(prod["capacity"]["on_demand_base"], 2)
        self.assertTrue(prod["manual_reroute"])
        hosts = {e["host_header"] for e in (dev, staging, prod)}
        self.assertEqual(hosts, {"dev.api.example.com", "staging.api.example.com", "api.example.com"})


class BadFixtureTests(unittest.TestCase):
    def test_fixture_list_is_complete(self):
        self.assertEqual({p.name for p in FIXTURES.glob("bad-*.json")}, set(EXPECTED))

    def test_each_fixture_fails_with_exactly_its_rules(self):
        for name, rules in EXPECTED.items():
            with self.subTest(fixture=name):
                report = policy.check_file(FIXTURES / name)
                self.assertFalse(report.ok)
                self.assertEqual({rule for rule, _ in report.findings}, rules, report.findings)


class RuleTests(unittest.TestCase):
    def test_all_at_once_allowed_outside_prod(self):
        self.assertTrue(policy.check_settings(load("dev")).ok)

    def test_production_alias_counts_as_prod(self):
        data = load("prod")
        data["environment"] = "Production"
        data["deployment_config_name"] = "CodeDeployDefault.ECSAllAtOnce"
        self.assertIn("BG001", {r for r, _ in policy.check_settings(data).findings})

    def test_ipv6_any_and_invalid_cidr(self):
        data = load("staging")
        data["test_listener_cidrs"] = ["::/0", "203.0.113.0/33", "10.0.0.1/8"]
        messages = [m for r, m in policy.check_settings(data).findings if r == "BG005"]
        self.assertEqual(len(messages), 3)

    def test_empty_cidrs(self):
        data = load("dev")
        data["test_listener_cidrs"] = []
        self.assertEqual({r for r, _ in policy.check_settings(data).findings}, {"BG005"})

    def test_bool_is_not_a_number(self):
        data = load("dev")
        data["termination_wait_minutes"] = True
        self.assertEqual({r for r, _ in policy.check_settings(data).findings}, {"BG000"})

    def test_prod_zero_thresholds(self):
        data = copy.deepcopy(load("prod"))
        data["alarms"]["target_5xx_threshold"] = 0
        self.assertEqual({r for r, _ in policy.check_settings(data).findings}, {"BG002"})

    def test_rollback_without_alarm_event_ok_when_alarms_off_outside_prod(self):
        data = load("dev")
        data["alarms"]["enabled"] = False
        data["auto_rollback"]["events"] = ["DEPLOYMENT_FAILURE"]
        self.assertTrue(policy.check_settings(data).ok)

    def test_unknown_rollback_event(self):
        data = load("dev")
        data["auto_rollback"]["events"].append("DEPLOYMENT_SUCCESS")
        self.assertEqual({r for r, _ in policy.check_settings(data).findings}, {"BG003"})

    def test_non_object(self):
        self.assertEqual(policy.check_settings([]).findings[0][0], "BG000")


if __name__ == "__main__":
    unittest.main()
