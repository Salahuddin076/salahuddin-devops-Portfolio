"""SARIF 2.1.0 structure as GitHub code scanning expects it."""

import datetime as dt
import json
import unittest

from helpers import FIXTURES

import check_plan

TODAY = dt.date(2026, 10, 14)
EXPECTED_NONCOMPLIANT = {"CSP-S3-001", "CSP-SG-001", "CSP-IAM-001", "CSP-RDS-001", "CSP-CT-001", "CSP-WAF-001"}


def sarif_for(fixture: str, with_exceptions: bool = True) -> dict:
    path = FIXTURES / fixture
    exceptions = check_plan.load_exceptions(check_plan.default_exceptions_path()) if with_exceptions else []
    report = check_plan.evaluate(json.loads(path.read_text()), str(path), exceptions, TODAY)
    return check_plan.render_sarif(report, path.read_text(), "projects/cloud-security-waf-automation/policy/fixtures/" + fixture)


class SarifStructureTests(unittest.TestCase):
    def setUp(self):
        self.doc = sarif_for("plan-noncompliant.json")
        self.run = self.doc["runs"][0]

    def test_top_level_keys(self):
        self.assertEqual(self.doc["version"], "2.1.0")
        self.assertIn("sarif-2.1.0", self.doc["$schema"])
        self.assertEqual(len(self.doc["runs"]), 1)
        json.dumps(self.doc)  # serialisable

    def test_driver_lists_every_rule(self):
        driver = self.run["tool"]["driver"]
        self.assertEqual(driver["name"], "check_plan")
        self.assertTrue(driver["version"])
        ids = [r["id"] for r in driver["rules"]]
        self.assertEqual(ids, list(check_plan.RULES))
        for r in driver["rules"]:
            for key in ("name", "shortDescription", "fullDescription", "help", "defaultConfiguration", "properties"):
                self.assertIn(key, r)
            self.assertIn(r["defaultConfiguration"]["level"], ("error", "warning", "note"))
            float(r["properties"]["security-severity"])

    def test_results_have_required_keys_and_valid_rule_ids(self):
        rule_ids = [r["id"] for r in self.run["tool"]["driver"]["rules"]]
        self.assertTrue(self.run["results"])
        for res in self.run["results"]:
            self.assertIn(res["ruleId"], rule_ids)
            self.assertEqual(rule_ids[res["ruleIndex"]], res["ruleId"])
            self.assertIn(res["level"], ("error", "warning", "note"))
            self.assertTrue(res["message"]["text"])
            loc = res["locations"][0]["physicalLocation"]
            self.assertTrue(loc["artifactLocation"]["uri"].startswith("projects/"))
            self.assertGreaterEqual(loc["region"]["startLine"], 1)
            self.assertTrue(res["partialFingerprints"])

    def test_expected_rule_ids_reported(self):
        self.assertEqual({r["ruleId"] for r in self.run["results"]}, EXPECTED_NONCOMPLIANT)

    def test_high_maps_to_error_medium_to_warning(self):
        levels = {r["ruleId"]: r["level"] for r in self.run["results"] if "suppressions" not in r}
        self.assertEqual(levels["CSP-IAM-001"], "error")
        self.assertEqual(levels["CSP-CT-001"], "warning")

    def test_start_line_points_at_the_resource(self):
        lines = (FIXTURES / "plan-noncompliant.json").read_text().splitlines()
        for res in self.run["results"]:
            line = lines[res["locations"][0]["physicalLocation"]["region"]["startLine"] - 1]
            self.assertIn(res["locations"][0]["logicalLocations"][0]["fullyQualifiedName"], line)

    def test_excepted_finding_is_suppressed_not_dropped(self):
        suppressed = [r for r in self.run["results"] if "suppressions" in r]
        self.assertEqual(len(suppressed), 1)
        self.assertEqual(suppressed[0]["ruleId"], "CSP-SG-001")
        self.assertEqual(suppressed[0]["suppressions"][0]["kind"], "external")
        self.assertIn("platform-team@example.com", suppressed[0]["suppressions"][0]["justification"])

    def test_expired_exception_is_a_notification(self):
        notes = self.run["invocations"][0]["toolExecutionNotifications"]
        self.assertTrue(any("aws_db_instance.reporting" in n["message"]["text"] for n in notes))

    def test_compliant_plan_has_no_results(self):
        run = sarif_for("plan-compliant.json", with_exceptions=False)["runs"][0]
        self.assertEqual(run["results"], [])
        self.assertNotIn("invocations", run)


if __name__ == "__main__":
    unittest.main()
