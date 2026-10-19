"""Terraform invariants that `validate` can't express (no terraform binary needed)."""

from __future__ import annotations

import re
import unittest

from helpers import TERRAFORM_DIR

NODE_GROUP = TERRAFORM_DIR / "modules" / "eks-arch-node-group"
ECR = TERRAFORM_DIR / "modules" / "ecr-multiarch"
EXAMPLE = TERRAFORM_DIR / "examples" / "mixed-fleet"
ROOTS = (NODE_GROUP, ECR, EXAMPLE)


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
        cls.node_group = tf(NODE_GROUP)
        cls.ecr = tf(ECR)
        cls.example = tf(EXAMPLE)
        cls.all = cls.node_group + cls.ecr + cls.example

    def test_versions_and_lock_files(self):
        for root in ROOTS:
            with self.subTest(root=root.name):
                versions = (root / "versions.tf").read_text()
                self.assertIn('required_version = ">= 1.9.0"', versions)
                self.assertIn('version = ">= 6.0, < 7.0"', versions)
                lock = (root / ".terraform.lock.hcl").read_text()
                self.assertIn('provider "registry.terraform.io/hashicorp/aws"', lock)
                self.assertIn('version     = "6.68.0"', lock)

    def test_no_credentials_or_real_account_ids(self):
        self.assertNotRegex(self.all, r"(?i)access_key|secret_key|aws_session_token|profile\s*=")
        for path in TERRAFORM_DIR.rglob("*"):
            if path.is_file() and ".terraform" not in path.parts:
                for account in re.findall(r"\b\d{12}\b", path.read_text()):
                    self.assertEqual(account, "123456789012", path)

    def test_architecture_variable_drives_ami_type_and_instances(self):
        arch_var = block((NODE_GROUP / "variables.tf").read_text(), 'variable "architecture"')
        self.assertIn('contains(["amd64", "arm64"], var.architecture)', arch_var)
        defaults = block(self.node_group, "arch_defaults = {")
        self.assertIn('ami_type       = "AL2023_x86_64_STANDARD"', defaults)
        self.assertIn('ami_type       = "AL2023_ARM_64_STANDARD"', defaults)
        self.assertIn("m6i.large", defaults)
        self.assertIn("m7g.large", defaults)

    def test_node_group_sets_architecture_label_from_the_ami_not_a_guess(self):
        # kubernetes.io/arch always matches the architecture variable: EKS also
        # sets it natively, so this label can never drift from the real value.
        self.assertIn('{ "kubernetes.io/arch" = var.architecture }', self.node_group)
        ng = block(self.node_group, 'resource "aws_eks_node_group" "this"')
        self.assertIn("labels = local.labels", ng)
        self.assertIn("ami_type        = local.ami_type", ng)

    def test_node_group_taint_is_optional_and_steady_state_is_untainted(self):
        taint_var = block((NODE_GROUP / "variables.tf").read_text(), 'variable "taint"')
        self.assertIn("default = null", taint_var)
        ng = block(self.node_group, 'resource "aws_eks_node_group" "this"')
        self.assertIn('dynamic "taint"', ng)
        self.assertIn("var.taint == null ? [] : [var.taint]", ng)

    def test_node_role_created_only_when_not_supplied(self):
        self.assertIn('count = var.node_role_arn == null ? 1 : 0', self.node_group)
        self.assertIn('"AmazonEKSWorkerNodePolicy"', self.node_group)
        self.assertIn('"AmazonEC2ContainerRegistryReadOnly"', self.node_group)
        self.assertIn('"AmazonEKS_CNI_Policy"', self.node_group)

    def test_desired_size_is_ignored_so_a_runbook_or_autoscaler_can_own_it(self):
        ng = block(self.node_group, 'resource "aws_eks_node_group" "this"')
        self.assertIn("ignore_changes = [scaling_config[0].desired_size]", ng)

    def test_ecr_repository_is_immutable_scanned_by_default(self):
        repo = block(self.ecr, 'resource "aws_ecr_repository" "this"')
        self.assertIn("image_tag_mutability = var.image_tag_mutability", repo)
        mutability_var = block((ECR / "variables.tf").read_text(), 'variable "image_tag_mutability"')
        self.assertIn('default     = "IMMUTABLE"', mutability_var)
        scan_var = block((ECR / "variables.tf").read_text(), 'variable "scan_on_push"')
        self.assertIn("default     = true", scan_var)

    def test_ecr_lifecycle_policy_is_optional_and_untagged_only(self):
        policy = block(self.ecr, 'resource "aws_ecr_lifecycle_policy" "untagged"')
        self.assertIn("count      = var.untagged_image_expiry_days > 0 ? 1 : 0", policy)
        self.assertIn('tagStatus   = "untagged"', policy)

    def test_every_variable_has_description_and_key_inputs_are_validated(self):
        for root, names in (
            (NODE_GROUP, ("name", "cluster_name", "architecture", "subnet_ids", "capacity_type", "scaling_config",
                          "taint", "node_role_arn")),
            (ECR, ("name", "image_tag_mutability", "untagged_image_expiry_days", "kms_key_arn")),
        ):
            variables = (root / "variables.tf").read_text()
            for name in re.findall(r'variable "([a-z_]+)"', variables):
                self.assertIn("description", block(variables, f'variable "{name}"'), f"{root.name}.{name}")
            for name in names:
                self.assertIn("validation", block(variables, f'variable "{name}"'), f"{root.name}.{name}")

    def test_example_wires_two_pools_and_the_shared_repo(self):
        self.assertIn('for_each = var.node_pools', self.example)
        node_pools_var = block((EXAMPLE / "variables.tf").read_text(), 'variable "node_pools"')
        self.assertIn('architecture   = "amd64"', node_pools_var)
        self.assertIn('architecture   = "arm64"', node_pools_var)
        self.assertIn("ecr_repository_arns = [module.ecr.repository_arn]", self.example)
        self.assertIn('source = "../../modules/eks-arch-node-group"', self.example)
        self.assertIn('source = "../../modules/ecr-multiarch"', self.example)

    def test_example_sets_default_tags(self):
        self.assertIn("default_tags", (EXAMPLE / "providers.tf").read_text())


if __name__ == "__main__":
    unittest.main()
