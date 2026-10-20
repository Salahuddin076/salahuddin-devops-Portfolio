"""Static assertions over terraform/modules/identity-bindings: the same
ServiceAccount name/namespace must bind cleanly to all three clouds' native
workload identity, with no static cloud credential ever created.
"""

from __future__ import annotations

import re
import unittest

from helpers import TERRAFORM_DIR

MODULE_DIR = TERRAFORM_DIR / "modules" / "identity-bindings"
EXAMPLE_DIR = TERRAFORM_DIR / "examples" / "reference"


def _read(path) -> str:
    return path.read_text()


def _all_tf_text(directory) -> str:
    return "\n".join(_read(p) for p in sorted(directory.glob("*.tf")))


class AwsIdentityBindingTests(unittest.TestCase):
    def setUp(self):
        self.aws_tf = _read(MODULE_DIR / "aws.tf")

    def test_uses_web_identity_federation_not_a_static_user(self):
        self.assertIn("AssumeRoleWithWebIdentity", self.aws_tf)
        self.assertNotIn('resource "aws_iam_access_key"', self.aws_tf)
        self.assertNotIn('resource "aws_iam_user"', self.aws_tf)

    def test_trust_policy_scoped_to_one_service_account_subject(self):
        self.assertIn("service_account_namespace", self.aws_tf)
        self.assertIn("service_account_name", self.aws_tf)
        self.assertIn(":sub", self.aws_tf)

    def test_audience_is_sts_amazonaws_com(self):
        self.assertIn("sts.amazonaws.com", self.aws_tf)


class AzureIdentityBindingTests(unittest.TestCase):
    def setUp(self):
        self.azure_tf = _read(MODULE_DIR / "azure.tf")

    def test_uses_federated_credential_not_a_client_secret(self):
        self.assertIn("azurerm_federated_identity_credential", self.azure_tf)
        self.assertNotIn("client_secret", self.azure_tf.lower())
        self.assertNotIn("azuread_application_password", self.azure_tf)

    def test_federated_credential_subject_matches_kubernetes_convention(self):
        self.assertIn("system:serviceaccount:", self.azure_tf)

    def test_audience_is_the_azure_ad_token_exchange_audience(self):
        self.assertIn("api://AzureADTokenExchange", self.azure_tf)


class GcpIdentityBindingTests(unittest.TestCase):
    def setUp(self):
        self.gcp_tf = _read(MODULE_DIR / "gcp.tf")

    def test_uses_workload_identity_binding_not_a_service_account_key(self):
        self.assertIn("workloadIdentityUser", self.gcp_tf)
        self.assertNotIn('resource "google_service_account_key"', self.gcp_tf)

    def test_member_uses_the_fixed_workload_identity_pool_suffix(self):
        self.assertIn(".svc.id.goog[", self.gcp_tf)


class SharedServiceAccountIdentityTests(unittest.TestCase):
    """The portability claim: one ServiceAccount name/namespace, three clouds."""

    def setUp(self):
        self.variables_tf = _read(MODULE_DIR / "variables.tf")
        self.module_text = _all_tf_text(MODULE_DIR)

    def test_service_account_name_and_namespace_default_to_portable_service(self):
        self.assertIn('variable "service_account_name"', self.variables_tf)
        self.assertIn('variable "service_account_namespace"', self.variables_tf)
        self.assertIn('default     = "portable-service"', self.variables_tf)

    def test_all_three_clouds_reference_the_same_service_account_variables(self):
        for var in ("service_account_name", "service_account_namespace"):
            self.assertGreaterEqual(
                self.module_text.count(f"var.{var}"), 3,
                f"expected {var} referenced by all three cloud resource sets",
            )

    def test_no_real_looking_account_identifiers(self):
        # Only documentation-safe placeholder account ids are allowed.
        account_ids = set(re.findall(r"\b\d{12}\b", self.module_text))
        self.assertLessEqual(account_ids, {"111111111111", "000000000000"})


class ReferenceExampleTests(unittest.TestCase):
    def setUp(self):
        self.main_tf = _read(EXAMPLE_DIR / "main.tf")

    def test_wires_the_identity_bindings_module(self):
        self.assertIn('module "identity_bindings"', self.main_tf)

    def test_versions_pin_all_three_providers(self):
        versions_tf = _read(EXAMPLE_DIR / "versions.tf")
        for provider in ("hashicorp/aws", "hashicorp/azurerm", "hashicorp/google"):
            self.assertIn(provider, versions_tf)

    def test_lock_files_are_committed(self):
        for directory in (MODULE_DIR, EXAMPLE_DIR):
            self.assertTrue((directory / ".terraform.lock.hcl").exists(), f"missing lock file in {directory}")

    def test_outputs_feed_each_clouds_values_overlay(self):
        outputs_tf = _read(MODULE_DIR / "outputs.tf")
        self.assertIn('output "aws_role_arn"', outputs_tf)
        self.assertIn('output "azure_client_id"', outputs_tf)
        self.assertIn('output "gcp_service_account_email"', outputs_tf)


if __name__ == "__main__":
    unittest.main()
