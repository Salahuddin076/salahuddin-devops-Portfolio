"""Terraform invariants that `validate` can't express (no terraform binary needed)."""

from __future__ import annotations

import re
import unittest

from helpers import TERRAFORM_DIR

MODULE = TERRAFORM_DIR / "modules" / "secrets-store-csi"
EXAMPLE = TERRAFORM_DIR / "examples" / "basic"
ROOTS = (MODULE, EXAMPLE)


def tf(directory):
    return "\n".join(p.read_text() for p in sorted(directory.glob("*.tf")))


def block(text, header):
    """The body of the first block starting with `header`, by brace matching."""
    start = text.index(header)
    i, depth = text.index("{", start), 0
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[i:j + 1]
    raise ValueError(header)


class TerraformStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = tf(MODULE)
        cls.all = cls.module + tf(EXAMPLE)

    def test_versions_and_lock_files(self):
        for root in ROOTS:
            with self.subTest(root=root.name):
                versions = (root / "versions.tf").read_text()
                self.assertIn('required_version = ">= 1.9.0"', versions)
                self.assertIn('version = ">= 6.0, < 7.0"', versions)
                lock = (root / ".terraform.lock.hcl").read_text()
                self.assertIn('provider "registry.terraform.io/hashicorp/aws"', lock)
                self.assertIn('version     = "6.68.0"', lock)
                self.assertNotIn("hashicorp/helm", lock)

    def test_no_credentials_or_real_account_ids(self):
        self.assertNotRegex(self.all, r"(?i)access_key|secret_key|aws_session_token|profile\s*=")
        for path in TERRAFORM_DIR.rglob("*"):
            if path.is_file() and ".terraform" not in path.parts:
                for account in re.findall(r"\b\d{12}\b", path.read_text()):
                    self.assertEqual(account, "123456789012", path)

    def test_secrets_without_versions_encrypted_with_the_cmk(self):
        self.assertNotRegex(self.module, r'resource\s+"aws_secretsmanager_secret_version"')
        for name in ("db", "api_key"):
            body = block(self.module, f'resource "aws_secretsmanager_secret" "{name}"')
            self.assertIn("kms_key_id              = aws_kms_key.secrets.arn", body)
        self.assertIn("enable_key_rotation     = true", self.module)

    def test_rotation_is_optional_and_never_immediate(self):
        body = block(self.module, 'resource "aws_secretsmanager_secret_rotation" "db"')
        self.assertIn("count = var.rotation_lambda_arn == null ? 0 : 1", body)
        self.assertIn("rotate_immediately  = false", body)

    def test_policy_is_two_actions_on_two_arns_plus_viaservice_decrypt(self):
        body = block(self.module, 'data "aws_iam_policy_document" "read_secrets"')
        actions = [a for line in re.findall(r"actions\s*=\s*\[([^\]]*)\]", body)
                   for a in re.findall(r'"([^"]+)"', line)]
        self.assertEqual(sorted(actions), ["kms:Decrypt", "secretsmanager:DescribeSecret", "secretsmanager:GetSecretValue"])
        self.assertIn("aws_secretsmanager_secret.db.arn", body)
        self.assertIn("aws_secretsmanager_secret.api_key.arn", body)
        self.assertNotIn('"*"', body)
        self.assertIn('variable = "kms:ViaService"', body)
        self.assertIn('"secretsmanager.${data.aws_region.current.region}.amazonaws.com"', body)

    def test_pod_identity_not_irsa(self):
        assume = block(self.module, 'data "aws_iam_policy_document" "assume"')
        self.assertIn('"pods.eks.amazonaws.com"', assume)
        self.assertIn('"sts:TagSession"', assume)
        self.assertIn("aws:SourceArn", assume)
        assoc = block(self.module, 'resource "aws_eks_pod_identity_association" "app"')
        self.assertIn("service_account = var.service_account", assoc)
        for irsa in ("aws_iam_openid_connect_provider", "AssumeRoleWithWebIdentity", "eks.amazonaws.com/role-arn"):
            self.assertNotIn(irsa, self.all)

    def test_csi_addon_with_rotation_and_sync_variables(self):
        body = block(self.module, 'resource "aws_eks_addon" "secrets_store_csi"')
        self.assertIn('addon_name                  = "aws-secrets-store-csi-driver-provider"', body)
        self.assertIn("configuration_values        = jsonencode(local.csi_addon_configuration)", body)
        cfg = block(self.module, "csi_addon_configuration = {")
        for expected in ('"secrets-store-csi-driver"', "enabled = var.sync_secret_enabled",
                         "enableSecretRotation = var.enable_secret_rotation",
                         "rotationPollInterval = var.rotation_poll_interval"):
            self.assertIn(expected, cfg)
        self.assertNotIn("helm_release", self.all)

    def test_every_variable_has_description_and_inputs_are_validated(self):
        variables = (MODULE / "variables.tf").read_text()
        names = re.findall(r'variable "([a-z_]+)"', variables)
        for name in names:
            self.assertIn("description", block(variables, f'variable "{name}"'), name)
        for name in ("name", "cluster_name", "rotation_poll_interval", "db_secret_name", "api_key_secret_name",
                     "recovery_window_in_days", "rotation_lambda_arn", "rotation_days", "namespace", "service_account"):
            self.assertIn("validation", block(variables, f'variable "{name}"'), name)

    def test_example_sets_default_tags(self):
        self.assertIn("default_tags", (EXAMPLE / "providers.tf").read_text())


if __name__ == "__main__":
    unittest.main()
