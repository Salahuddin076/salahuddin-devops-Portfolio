"""Text-level guards on Terraform invariants that `terraform validate` cannot see."""

import re
import unittest

from helpers import PROJECT

TF = PROJECT / "terraform"
WAF = TF / "modules" / "waf"
DETECT = TF / "modules" / "detective-response"


def read(*parts):
    return "\n".join(p.read_text() for p in parts)


class WafModuleTests(unittest.TestCase):
    main = read(WAF / "main.tf")
    variables = read(WAF / "variables.tf")

    def test_log_group_name_has_required_prefix(self):
        self.assertIn('log_group_name = "aws-waf-logs-${var.name_prefix}"', self.main)

    def test_authorization_and_cookie_redacted_by_default(self):
        self.assertIn('default     = ["authorization", "cookie"]', self.variables)
        self.assertIn("redacted_fields", self.main)

    def test_scope_validation(self):
        self.assertIn('contains(["REGIONAL", "CLOUDFRONT"], var.scope)', self.variables)
        self.assertRegex(self.variables, r'variable "scope" \{[^}]*default\s+= "REGIONAL"')

    def test_every_mode_variable_is_validated_to_count_or_block(self):
        for var in ("block_list_mode", "rate_limit_mode"):
            self.assertRegex(self.variables, rf'contains\(\["count", "block"\], var\.{var}\)')
        self.assertIn('contains(["count", "block"], g.mode)', self.variables)

    def test_managed_groups_present_and_sqli_optional(self):
        for g in ("AWSManagedRulesCommonRuleSet", "AWSManagedRulesKnownBadInputsRuleSet",
                  "AWSManagedRulesAmazonIpReputationList", "AWSManagedRulesSQLiRuleSet"):
            self.assertIn(g, self.variables)
        self.assertRegex(self.variables, r'AWSManagedRulesSQLiRuleSet\s+= \{[^}]*enabled = false')

    def test_rate_rule_keyed_on_ip(self):
        self.assertIn('aggregate_key_type    = "IP"', self.main)

    def test_blocked_requests_alarm(self):
        self.assertIn('metric_name         = "BlockedRequests"', self.main)
        self.assertIn('namespace           = "AWS/WAFV2"', self.main)


class DetectiveModuleTests(unittest.TestCase):
    main = read(DETECT / "main.tf")
    variables = read(DETECT / "variables.tf")

    def test_severity_bands(self):
        self.assertRegex(self.variables, r'variable "guardduty_page_min_severity" \{[^}]*default\s+= 7\b')
        self.assertRegex(self.variables, r'variable "guardduty_ticket_min_severity" \{[^}]*default\s+= 4\b')
        self.assertIn('numeric = [">=", var.guardduty_ticket_min_severity, "<", var.guardduty_page_min_severity]', self.main)

    def test_security_hub_filters(self):
        self.assertIn('Workflow    = { Status = ["NEW"] }', self.main)
        self.assertIn('Label = ["CRITICAL"]', self.main)
        self.assertIn('Label = ["HIGH"]', self.main)
        self.assertIn("aws-foundational-security-best-practices/v/1.0.0", self.main)

    def test_topics_encrypted_with_cmk_usable_by_eventbridge(self):
        self.assertEqual(len(re.findall(r"kms_master_key_id = aws_kms_key\.sns\.arn", self.main)), 2)
        self.assertIn('"events.amazonaws.com"', self.main)
        self.assertIn('"kms:GenerateDataKey*"', self.main)
        self.assertIn("enable_key_rotation     = true", self.main)

    def test_no_rotation_lambda_is_built(self):
        self.assertNotIn('resource "aws_lambda_function"', self.main)
        self.assertIn('resource "aws_secretsmanager_secret_rotation"', self.main)


class HygieneTests(unittest.TestCase):
    def test_no_credentials_or_real_account_ids(self):
        for path in TF.rglob("*.tf*"):
            if ".terraform" in path.parts or path.name == ".terraform.lock.hcl":
                continue
            text = path.read_text()
            with self.subTest(path=path.name):
                self.assertNotRegex(text, r"(access_key|secret_key)\s*=")
                for acct in re.findall(r"\b\d{12}\b", text):
                    self.assertEqual(acct, "123456789012")

    def test_provider_constraint(self):
        for versions in TF.rglob("versions.tf"):
            with self.subTest(path=str(versions.parent.name)):
                self.assertIn('version = ">= 6.0, < 7.0"', versions.read_text())
                self.assertIn("required_version", versions.read_text())


if __name__ == "__main__":
    unittest.main()
