"""Terraform invariants that `terraform validate` can't see."""

import json
import re
import unittest

from helpers import PROJECT, TERRAFORM_DIR

MODULES = TERRAFORM_DIR / "modules"
REGIONAL = MODULES / "regional-stack"
GLOBAL = MODULES / "global-data"
VALIDATED_DIRS = [
    "environments/primary",
    "environments/dr",
    "environments/global",
    "modules/regional-stack",
    "modules/global-data/validation-harness",
]


def read_dir(path):
    return "\n".join(p.read_text() for p in sorted(path.glob("*.tf")))


def all_tf():
    return {p: p.read_text() for p in TERRAFORM_DIR.rglob("*.tf") if ".terraform" not in p.parts}


class LayoutTests(unittest.TestCase):
    def test_lock_files_committed_for_every_validated_dir(self):
        for d in VALIDATED_DIRS:
            with self.subTest(d):
                lock = (TERRAFORM_DIR / d / ".terraform.lock.hcl").read_text()
                self.assertIn('provider "registry.terraform.io/hashicorp/aws"', lock)
                self.assertIn('version     = "6.68.0"', lock)

    def test_versions_pin_terraform_and_aws_6(self):
        for p, text in all_tf().items():
            if p.name != "versions.tf" and "required_providers" not in text:
                continue
            with self.subTest(str(p.relative_to(TERRAFORM_DIR))):
                self.assertRegex(text, r'required_version\s*=\s*">= 1\.(9|1[0-9])\.0"')
                self.assertRegex(text, r'version\s*=\s*">= 6\.0, < 7\.0"')

    def test_global_data_takes_two_aliased_providers(self):
        self.assertIn("configuration_aliases = [aws.primary, aws.dr]", (GLOBAL / "versions.tf").read_text())
        harness = (GLOBAL / "validation-harness" / "main.tf").read_text()
        self.assertIn("aws.primary = aws.primary", harness)
        self.assertIn("aws.dr      = aws.dr", harness)

    def test_environments_set_default_tags_and_no_credentials(self):
        for env in ("primary", "dr", "global"):
            with self.subTest(env):
                self.assertIn("default_tags", (TERRAFORM_DIR / "environments" / env / "providers.tf").read_text())
        for p, text in all_tf().items():
            with self.subTest(str(p.relative_to(TERRAFORM_DIR))):
                self.assertNotRegex(text, r"\b(access_key|secret_key|profile|shared_credentials_files)\s*=")

    def test_only_placeholder_account_ids(self):
        # 12 digits not inside a longer token (UUID tails like ...-000000000001 are fine)
        pattern = re.compile(r"(?<![-\w])\d{12}(?![-\w])")
        for p in PROJECT.rglob("*"):
            if not p.is_file() or ".terraform" in p.parts or p.suffix in (".hcl", ".pyc"):
                continue
            ids = set(pattern.findall(p.read_text(errors="ignore")))
            with self.subTest(str(p.relative_to(PROJECT))):
                self.assertLessEqual(ids, {"123456789012"})


class RegionalStackTests(unittest.TestCase):
    text = read_dir(REGIONAL)

    def test_three_tier_vpc_with_nat_toggle(self):
        for res in ('resource "aws_subnet" "public"', 'resource "aws_subnet" "private"',
                    'resource "aws_subnet" "data"', "nat_gateway_per_az"):
            self.assertIn(res, self.text)
        self.assertIn('"kubernetes.io/role/elb"', self.text)

    def test_eks_uses_access_entries_not_aws_auth(self):
        self.assertIn('authentication_mode                         = "API"', self.text)
        self.assertIn('resource "aws_eks_access_entry"', self.text)
        self.assertNotIn('"aws-auth"', self.text)
        self.assertNotIn("kubernetes_config_map", self.text)

    def test_eks_version_and_node_scaling_are_validated(self):
        variables = (REGIONAL / "variables.tf").read_text()
        self.assertIn('variable "kubernetes_version"', variables)
        self.assertIn("var.node_scaling.min <= var.node_scaling.desired", variables)

    def test_pod_identity_for_app_and_lb_controller(self):
        self.assertEqual(self.text.count('resource "aws_eks_pod_identity_association"'), 2)
        self.assertIn('service_account = "aws-load-balancer-controller"', self.text)
        self.assertIn("pods.eks.amazonaws.com", self.text)
        self.assertIn('addon_name   = "eks-pod-identity-agent"', self.text)

    def test_alb_is_not_created_by_terraform(self):
        for p, text in all_tf().items():
            with self.subTest(str(p.relative_to(TERRAFORM_DIR))):
                self.assertNotRegex(text, r'resource\s+"aws_(lb|alb|lb_listener|lb_target_group)"')

    def test_lb_controller_policy_is_valid_json(self):
        raw = (REGIONAL / "policies" / "aws-load-balancer-controller.json.tftpl").read_text()
        policy = json.loads(raw.replace("${partition}", "aws"))
        self.assertEqual(policy["Version"], "2012-10-17")
        conditioned = [s for s in policy["Statement"] if "elbv2.k8s.aws/cluster" in json.dumps(s)]
        self.assertGreaterEqual(len(conditioned), 5)

    def test_valkey_is_regional_and_encrypted(self):
        self.assertIn('engine               = "valkey"', self.text)
        self.assertIn("transit_encryption_enabled = true", self.text)
        self.assertIn("at_rest_encryption_enabled = true", self.text)
        for p, text in all_tf().items():
            self.assertNotIn("aws_elasticache_global_replication_group", text)

    def test_network_policy_enforcement_enabled_in_cni(self):
        self.assertIn('enableNetworkPolicy = "true"', self.text)


class GlobalDataTests(unittest.TestCase):
    text = read_dir(GLOBAL)

    def test_aurora_global_database_with_per_region_keys(self):
        self.assertIn('resource "aws_rds_global_cluster" "this"', self.text)
        self.assertEqual(self.text.count("global_cluster_identifier = aws_rds_global_cluster.this.id"), 2)
        self.assertIn("kms_key_id        = var.primary.kms_key_arn", self.text)
        self.assertIn("kms_key_id        = var.dr.kms_key_arn", self.text)
        self.assertIn("ignore_changes = [global_cluster_identifier, replication_source_identifier]", self.text)

    def test_password_never_in_state(self):
        self.assertIn('ephemeral "aws_secretsmanager_random_password" "db"', self.text)
        self.assertIn("master_password_wo ", self.text)
        self.assertIn("secret_string_wo ", self.text)
        self.assertNotRegex(self.text, r"\bmaster_password\s*=")

    def test_secret_replicated_to_dr(self):
        self.assertRegex(self.text, r"replica \{\s*region\s*= local\.dr_region\s*kms_key_id = var\.dr\.kms_key_arn")

    def test_s3_crr_versioned_with_optional_rtc(self):
        self.assertEqual(self.text.count('resource "aws_s3_bucket_versioning"'), 2)
        self.assertIn('resource "aws_s3_bucket_replication_configuration" "primary_to_dr"', self.text)
        self.assertIn('dynamic "replication_time"', self.text)
        self.assertIn("for_each = var.s3_replication_time_control ? [1] : []", self.text)
        self.assertIn("replica_kms_key_id = var.dr.kms_key_arn", self.text)

    def test_route53_failover_with_deep_health_checks(self):
        self.assertIn('type = each.value.initial_role', self.text)
        self.assertIn('initial_role = "PRIMARY"', self.text)
        self.assertIn('initial_role = "SECONDARY"', self.text)
        self.assertIn('health_check_path = optional(string, "/healthz/ready")', self.text)
        self.assertIn("ignore_changes = [failover_routing_policy]", self.text)
        # phase 1 creates nothing: the ALBs don't exist yet
        self.assertIn("dns_enabled = var.dns != null && try(var.dns.primary_alb, null) != null", self.text)


if __name__ == "__main__":
    unittest.main()
