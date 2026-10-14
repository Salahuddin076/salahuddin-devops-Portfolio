"""Terraform invariants that validate can't see: pins, no plaintext in state, scoping."""

from __future__ import annotations

import re
import unittest

from helpers import MODULE_DIR, TERRAFORM_DIR

EXAMPLE_DIR = TERRAFORM_DIR / "examples" / "basic"


def tf(directory):
    return "\n".join(p.read_text() for p in sorted(directory.glob("*.tf")))


MODULE = tf(MODULE_DIR)
EXAMPLE = tf(EXAMPLE_DIR)


def block(text, kind, name):
    start = text.index(f'{kind} "{name}"') if kind in ("variable", "output") else text.index(f'"{kind}" "{name}"')
    depth, i = 0, text.index("{", start)
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[start:j + 1]
    raise ValueError(name)


class PinsTests(unittest.TestCase):
    def test_provider_and_terraform_versions(self):
        for d in (MODULE_DIR, EXAMPLE_DIR):
            with self.subTest(d=d.name):
                text = tf(d)
                self.assertIn('version = ">= 6.0, < 7.0"', text)
                self.assertIn('required_version = ">= 1.11.0"', text)
                lock = (d / ".terraform.lock.hcl").read_text()
                self.assertIn('version     = "6.68.0"', lock)
                self.assertNotIn("hashicorp/helm", text + lock, "KEDA is installed with helm, not Terraform")

    def test_no_credentials_and_placeholder_account(self):
        for text in (MODULE, EXAMPLE):
            self.assertNotRegex(text, r"access_key|secret_key|AKIA[0-9A-Z]{16}")
            for account in re.findall(r"(?<!\d)\d{12}(?!\d)", text):
                self.assertEqual(account, "123456789012")


class SecretsTests(unittest.TestCase):
    def test_no_secret_versions_or_plaintext_arguments(self):
        self.assertNotIn('resource "aws_secretsmanager_secret_version"', MODULE)
        rg = block(MODULE, "aws_elasticache_replication_group", "queue")
        self.assertIn("auth_token_wo ", rg)
        self.assertIn("auth_token_wo_version", rg)
        self.assertNotRegex(rg, r"\bauth_token\s*=")
        self.assertIn('ephemeral "aws_secretsmanager_secret_version" "redis_auth"', MODULE)

    def test_rds_manages_its_master_password(self):
        db = block(MODULE, "aws_db_instance", "n8n")
        self.assertIn("manage_master_user_password   = true", db)
        self.assertNotRegex(db, r"\bpassword(_wo)?\s*=")
        for setting in ("storage_encrypted     = true", "deletion_protection       = var.db_deletion_protection",
                        "skip_final_snapshot       = false", "publicly_accessible    = false",
                        "backup_retention_period   = var.db_backup_retention_days"):
            self.assertIn(setting, db)

    def test_cache_encryption_and_multi_az(self):
        rg = block(MODULE, "aws_elasticache_replication_group", "queue")
        for setting in ('engine               = "valkey"', "transit_encryption_enabled = true",
                        'transit_encryption_mode    = "required"', "at_rest_encryption_enabled = true",
                        "multi_az_enabled           = var.cache_multi_az"):
            self.assertIn(setting, rg)
        self.assertNotIn("num_node_groups", rg, "cluster mode off: the Bull key stays bull:jobs:wait")

    def test_three_secrets_on_the_cmk(self):
        for name in ("encryption_key", "db_app", "redis_auth"):
            self.assertIn("kms_key_id              = aws_kms_key.n8n.arn", block(MODULE, "aws_secretsmanager_secret", name))


class IamTests(unittest.TestCase):
    def test_n8n_role_reads_exactly_three_secrets(self):
        doc = block(MODULE, "aws_iam_policy_document", "n8n")
        self.assertEqual(sorted(re.findall(r"aws_secretsmanager_secret\.(\w+)\.arn", doc)),
                         ["db_app", "encryption_key", "redis_auth"])
        self.assertNotIn("master_user_secret", doc)
        self.assertIn("kms:ViaService", doc)
        self.assertNotIn('"*"', doc)

    def test_keda_role_reads_only_the_redis_token(self):
        doc = block(MODULE, "aws_iam_policy_document", "keda")
        self.assertEqual(re.findall(r"aws_secretsmanager_secret\.(\w+)\.arn", doc), ["redis_auth"])
        self.assertIn('["secretsmanager:GetSecretValue"]', doc)

    def test_pod_identity_trust(self):
        trust = block(MODULE, "aws_iam_policy_document", "pod_identity_trust")
        self.assertIn("pods.eks.amazonaws.com", trust)
        self.assertIn("aws:SourceArn", trust)
        self.assertIn("aws:SourceAccount", trust)
        self.assertEqual(MODULE.count('resource "aws_eks_pod_identity_association"'), 2)


class NetworkTests(unittest.TestCase):
    def test_data_stores_accept_security_groups_not_cidrs(self):
        for rule in ("db_from_clients", "cache_from_clients"):
            body = block(MODULE, "aws_vpc_security_group_ingress_rule", rule)
            self.assertIn("referenced_security_group_id", body)
            self.assertNotIn("cidr_ipv4", body)

    def test_inputs_are_documented(self):
        for name in re.findall(r'variable "(\w+)"', MODULE):
            self.assertIn("description", block(MODULE, "variable", name), name)


if __name__ == "__main__":
    unittest.main()
