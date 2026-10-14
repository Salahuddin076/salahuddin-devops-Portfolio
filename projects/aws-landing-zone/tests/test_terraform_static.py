"""Terraform invariants that `terraform validate` cannot see.

Text-level checks on the .tf files: provider constraints, lock files, the
route-table isolation matrix, account protection, and synthetic values only.
"""

import json
import re
import unittest

from helpers import POLICY_DIR, PROJECT, TERRAFORM

MODULES = sorted(p for p in (TERRAFORM / "modules").iterdir() if p.is_dir())
ENVIRONMENTS = sorted(p for p in (TERRAFORM / "environments").iterdir() if p.is_dir())
HARNESS = TERRAFORM / "modules" / "log-archive" / "validation-harness"
ROOTS = MODULES + ENVIRONMENTS + [HARNESS]
ALL_TF = sorted(TERRAFORM.rglob("*.tf"))
PLACEHOLDER_ACCOUNTS = {d * 12 for d in "123456789"} | {"123456789012"}
MARKERS = r"\b(" + "TO" + "DO|" + "FIX" + "ME)\b"  # split so this file does not match itself


def read(path):
    return path.read_text()


class LayoutTests(unittest.TestCase):
    def test_expected_modules_and_environments(self):
        self.assertEqual([m.name for m in MODULES], [
            "account-baseline", "guardrails", "identity-center", "log-archive", "network-hub", "organization", "spoke-vpc"])
        self.assertEqual([e.name for e in ENVIRONMENTS], ["management", "shared-services", "workload-baseline"])

    def test_every_root_has_lock_file_pinned_to_aws_6(self):
        for d in ROOTS:
            with self.subTest(dir=d.name):
                lock = read(d / ".terraform.lock.hcl")
                self.assertRegex(lock, r'version\s+=\s+"6\.\d+\.\d+"')

    def test_provider_constraint_everywhere(self):
        for d in MODULES + ENVIRONMENTS:
            with self.subTest(dir=d.name):
                self.assertIn('version = ">= 6.0, < 7.0"', read(d / "versions.tf").replace("  ", " "))

    def test_environments_have_providers_examples_and_commented_backend(self):
        for d in ENVIRONMENTS:
            with self.subTest(env=d.name):
                self.assertIn("assume_role {", read(d / "providers.tf"))
                self.assertTrue((d / "terraform.tfvars.example").is_file())
                versions = read(d / "versions.tf")
                self.assertIn('# backend "s3" {', versions)
                self.assertNotRegex(versions, r'(?m)^\s*backend\s+"s3"')

    def test_no_credentials_in_providers(self):
        for path in ALL_TF:
            with self.subTest(file=str(path.relative_to(TERRAFORM))):
                self.assertNotRegex(read(path), r"(access_key|secret_key|profile)\s*=")

    def test_no_empty_files_or_todo_markers(self):
        for path in [p for p in PROJECT.rglob("*") if p.is_file() and ".terraform" not in p.parts and "__pycache__" not in p.parts]:
            with self.subTest(file=str(path.relative_to(PROJECT))):
                text = path.read_text(errors="ignore")
                self.assertTrue(text.strip(), "empty file")
                self.assertNotRegex(text, MARKERS)


class SyntheticValueTests(unittest.TestCase):
    def test_only_placeholder_account_ids(self):
        files = [p for p in PROJECT.rglob("*") if p.is_file() and p.suffix in {".tf", ".json", ".example", ".md", ".py", ".tftpl"}
                 and ".terraform" not in p.parts]
        for path in files:
            for match in re.findall(r"(?<![0-9])[0-9]{12}(?![0-9])", path.read_text()):
                with self.subTest(file=str(path.relative_to(PROJECT)), id=match):
                    self.assertIn(match, PLACEHOLDER_ACCOUNTS)

    def test_only_example_com_emails(self):
        for path in [p for p in PROJECT.rglob("*") if p.is_file() and p.suffix in {".tf", ".example", ".json", ".md"}]:
            for email in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", path.read_text()):
                with self.subTest(file=str(path.relative_to(PROJECT)), email=email):
                    self.assertTrue(email.endswith("@example.com"))


class OrganizationTests(unittest.TestCase):
    MAIN = read(TERRAFORM / "modules" / "organization" / "main.tf")

    def test_accounts_are_never_closed_or_destroyed_by_terraform(self):
        block = self.MAIN[self.MAIN.index('resource "aws_organizations_account" "this"'):]
        block = block[:block.index("\n}\n")]
        self.assertIn("close_on_deletion          = false", block)
        self.assertIn("prevent_destroy = true", block)

    def test_policy_types_and_trusted_access(self):
        self.assertIn('"SERVICE_CONTROL_POLICY"', self.MAIN)
        self.assertIn('"TAG_POLICY"', self.MAIN)
        variables = read(TERRAFORM / "modules" / "organization" / "variables.tf")
        for svc in ("cloudtrail", "config", "guardduty", "securityhub", "sso"):
            self.assertIn(f'"{svc}.amazonaws.com"', variables)

    def test_ou_keys_match_attachment_hierarchy(self):
        hierarchy = json.loads(read(POLICY_DIR / "attachments.json"))["hierarchy"]
        ou_keys = set(re.findall(r"^\s{4}(\w+)\s+=\s+\"[A-Z]\w+\"$", self.MAIN, re.M))
        self.assertEqual(ou_keys | {"root"}, set(hierarchy))
        self.assertIn('parent_id = aws_organizations_organizational_unit.top["workloads"].id', self.MAIN)
        self.assertEqual(hierarchy["prod"], "workloads")
        self.assertEqual(hierarchy["nonprod"], "workloads")


class NetworkIsolationTests(unittest.TestCase):
    MAIN = read(TERRAFORM / "modules" / "network-hub" / "main.tf")

    def matrix(self):
        block = self.MAIN[self.MAIN.index("propagate_into = {"):]
        block = block[:block.index("}")]
        return {k: re.findall(r'"(\w+)"', v) for k, v in re.findall(r"(\w+)\s+=\s+(\[[^\]]*\])", block)}

    def test_prod_and_nonprod_never_propagate_into_each_other(self):
        m = self.matrix()
        self.assertEqual(set(m), {"prod", "nonprod", "shared"})
        self.assertNotIn("nonprod", m["prod"])
        self.assertNotIn("prod", m["nonprod"])

    def test_shared_reaches_everyone_and_everyone_reaches_shared(self):
        m = self.matrix()
        self.assertEqual(set(m["shared"]), {"prod", "nonprod", "shared"})
        self.assertIn("shared", m["prod"])
        self.assertIn("shared", m["nonprod"])

    def test_no_default_route_table_and_blackholes(self):
        self.assertIn('default_route_table_association = "disable"', self.MAIN)
        self.assertIn('default_route_table_propagation = "disable"', self.MAIN)
        self.assertIn("blackhole                      = true", self.MAIN)
        variables = read(TERRAFORM / "modules" / "network-hub" / "variables.tf")
        self.assertIn('default     = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]', variables)

    def test_spokes_associate_with_their_own_environment(self):
        self.assertIn("aws_ec2_transit_gateway_route_table.this[var.spoke_vpcs[each.key].environment].id", self.MAIN)

    def test_overlap_check_and_precondition(self):
        self.assertIn('check "address_plan_has_no_overlaps"', self.MAIN)
        self.assertEqual(self.MAIN.count("length(local.overlapping_pairs) == 0"), 2)

    def test_ram_share_stays_inside_the_org(self):
        self.assertIn("allow_external_principals = false", self.MAIN)


class LogArchiveTests(unittest.TestCase):
    MAIN = read(TERRAFORM / "modules" / "log-archive" / "main.tf")

    def test_trail_settings(self):
        for setting in ("is_organization_trail         = true", "is_multi_region_trail         = true",
                        "enable_log_file_validation    = true", "kms_key_id"):
            self.assertIn(setting, self.MAIN)

    def test_bucket_protection(self):
        self.assertIn("object_lock_enabled = true", self.MAIN)
        self.assertIn('status = "Enabled"', self.MAIN)
        self.assertIn('storage_class = "GLACIER"', self.MAIN)
        self.assertIn('"aws:SecureTransport"', self.MAIN)
        self.assertIn('"aws:SourceOrgID"', self.MAIN)
        self.assertIn('default     = "GOVERNANCE"', read(TERRAFORM / "modules" / "log-archive" / "variables.tf"))

    def test_uses_both_provider_aliases(self):
        self.assertIn("provider = aws.management", self.MAIN)
        self.assertIn("provider = aws.log_archive", self.MAIN)
        self.assertNotRegex(self.MAIN, r'resource "[^"]+" "[^"]+" \{\n(?!  provider = aws\.)')


class GuardrailsWiringTests(unittest.TestCase):
    def test_management_reads_policy_data(self):
        main = read(TERRAFORM / "environments" / "management" / "main.tf")
        self.assertIn('file("${local.policy_dir}/attachments.json")', main)
        self.assertIn('file("${local.policy_dir}/template-values.json")', main)

    def test_network_reads_cidr_plan(self):
        for env in ("shared-services", "workload-baseline"):
            self.assertIn("policy/cidr-plan.json", read(TERRAFORM / "environments" / env / "main.tf"))

    def test_guardrails_minify_and_size_check(self):
        main = read(TERRAFORM / "modules" / "guardrails" / "main.tf")
        self.assertIn("jsonencode(jsondecode(templatefile(", main)
        self.assertIn("length(each.value) <= 5120", main)

    def test_identity_center_admin_session_is_short(self):
        variables = read(TERRAFORM / "modules" / "identity-center" / "variables.tf")
        self.assertIn('AdministratorAccess = "PT1H"', variables)


if __name__ == "__main__":
    unittest.main()
