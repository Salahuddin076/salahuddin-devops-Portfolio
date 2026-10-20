"""Terraform invariants that `validate` can't express (no terraform binary needed)."""

from __future__ import annotations

import re
import unittest

from helpers import TERRAFORM_DIR

MODULES = TERRAFORM_DIR / "modules"
HUB = MODULES / "hub"
SPOKE = MODULES / "spoke"
AKS = MODULES / "aks"
PLATFORM = MODULES / "platform"
WORKLOAD_IDENTITY = MODULES / "workload-identity"
PIPELINE_IDENTITY = MODULES / "pipeline-identity"
EXAMPLE = TERRAFORM_DIR / "examples" / "reference"
ALL_ROOTS = (HUB, SPOKE, AKS, PLATFORM, WORKLOAD_IDENTITY, PIPELINE_IDENTITY, EXAMPLE)


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
        cls.hub = tf(HUB)
        cls.spoke = tf(SPOKE)
        cls.aks = tf(AKS)
        cls.platform = tf(PLATFORM)
        cls.workload_identity = tf(WORKLOAD_IDENTITY)
        cls.pipeline_identity = tf(PIPELINE_IDENTITY)
        cls.example = tf(EXAMPLE)
        cls.all = "\n".join([cls.hub, cls.spoke, cls.aks, cls.platform,
                              cls.workload_identity, cls.pipeline_identity, cls.example])

    # --- repo-wide hygiene ---------------------------------------------

    def test_versions_pin_azurerm_provider_in_every_root(self):
        for root in ALL_ROOTS:
            with self.subTest(root=root.name):
                versions = (root / "versions.tf").read_text()
                self.assertIn('required_version = ">= 1.9.0"', versions)
                self.assertIn('version = ">= 4.0, < 5.0"', versions)

    def test_no_client_secrets_or_connection_strings_anywhere(self):
        # Federated credentials only -- no azuread_application_password,
        # no azurerm_key_vault_secret literal, no inline connection string.
        self.assertNotRegex(self.all, r'resource\s+"azuread_application_password"')
        self.assertNotRegex(self.all, r"(?im)^\s*client_secret\s*=\s*\"[^$]")
        self.assertNotRegex(self.all, r"(?i)connection_string\s*=\s*\"(?!\\$)[^\"]{10,}")

    def test_no_service_principal_passwords(self):
        self.assertNotRegex(self.all, r'resource\s+"azuread_service_principal_password"')

    def test_every_variable_has_a_description(self):
        for root in ALL_ROOTS:
            variables_path = root / "variables.tf"
            if not variables_path.is_file():
                continue
            variables = variables_path.read_text()
            for name in re.findall(r'variable "([a-zA-Z_][a-zA-Z0-9_]*)"', variables):
                with self.subTest(root=root.name, variable=name):
                    self.assertIn("description", block(variables, f'variable "{name}"'))

    # --- hub: firewall + bastion ------------------------------------------

    def test_hub_has_fixed_name_subnets_for_firewall_and_bastion(self):
        self.assertIn('name                 = "AzureFirewallSubnet"', self.hub)
        self.assertIn('name                 = "AzureBastionSubnet"', self.hub)

    def test_firewall_policy_default_deny_with_explicit_allow_rule(self):
        self.assertIn('resource "azurerm_firewall_policy_rule_collection_group" "aks_egress"', self.hub)
        rule_group = block(self.hub, 'resource "azurerm_firewall_policy_rule_collection_group" "aks_egress"')
        self.assertIn('action   = "Allow"', rule_group)

    def test_firewall_is_shared_hub_resource_not_per_spoke(self):
        # Exactly one firewall resource lives in the hub module; spokes never
        # declare their own (see docs/cost.md: "share one hub across spokes").
        self.assertEqual(len(re.findall(r'resource\s+"azurerm_firewall"\s+"', self.hub)), 1)
        self.assertNotRegex(self.spoke, r'resource\s+"azurerm_firewall"\s+"')

    # --- spoke: forced tunneling + private endpoints subnet ---------------

    def test_spoke_forces_default_route_through_the_firewall(self):
        route_table = block(self.spoke, 'resource "azurerm_route_table" "forced_tunnel"')
        self.assertIn('address_prefix         = "0.0.0.0/0"', route_table)
        self.assertIn('next_hop_type          = "VirtualAppliance"', route_table)
        self.assertIn("next_hop_in_ip_address = var.firewall_private_ip", route_table)
        self.assertIn(
            'resource "azurerm_subnet_route_table_association" "aks"',
            self.spoke,
        )

    def test_spoke_has_dedicated_private_endpoints_subnet(self):
        pe_subnet = block(self.spoke, 'resource "azurerm_subnet" "private_endpoints"')
        self.assertIn('private_endpoint_network_policies = "Disabled"', pe_subnet)

    def test_spoke_peers_both_directions_with_hub(self):
        self.assertIn('resource "azurerm_virtual_network_peering" "spoke_to_hub"', self.spoke)
        self.assertIn('resource "azurerm_virtual_network_peering" "hub_to_spoke"', self.spoke)

    # --- aks: private, no local accounts, azure rbac, policy add-on -------

    def test_cluster_is_private(self):
        cluster = block(self.aks, 'resource "azurerm_kubernetes_cluster" "this"')
        self.assertIn("private_cluster_enabled             = true", cluster)
        self.assertIn("private_cluster_public_fqdn_enabled = false", cluster)

    def test_local_accounts_are_disabled(self):
        cluster = block(self.aks, 'resource "azurerm_kubernetes_cluster" "this"')
        self.assertIn("local_account_disabled = true", cluster)

    def test_azure_rbac_for_kubernetes_authorization_tied_to_entra_groups(self):
        cluster = block(self.aks, 'resource "azurerm_kubernetes_cluster" "this"')
        aad_block = block(cluster, "azure_active_directory_role_based_access_control {")
        self.assertIn("azure_rbac_enabled     = true", aad_block)
        self.assertIn("admin_group_object_ids = var.admin_group_object_ids", aad_block)

    def test_azure_policy_addon_enabled(self):
        cluster = block(self.aks, 'resource "azurerm_kubernetes_cluster" "this"')
        self.assertIn("azure_policy_enabled = true", cluster)

    def test_workload_identity_and_oidc_issuer_enabled(self):
        cluster = block(self.aks, 'resource "azurerm_kubernetes_cluster" "this"')
        self.assertIn("oidc_issuer_enabled       = true", cluster)
        self.assertIn("workload_identity_enabled = true", cluster)

    def test_key_vault_csi_driver_addon_enabled_with_rotation(self):
        cluster = block(self.aks, 'resource "azurerm_kubernetes_cluster" "this"')
        kv_provider = block(cluster, "key_vault_secrets_provider {")
        self.assertIn("secret_rotation_enabled  = true", kv_provider)

    def test_outbound_type_is_user_defined_routing_for_forced_tunneling(self):
        cluster = block(self.aks, 'resource "azurerm_kubernetes_cluster" "this"')
        network_profile = block(cluster, "network_profile {")
        self.assertIn('outbound_type     = "userDefinedRouting"', network_profile)

    def test_system_pool_is_separate_from_user_pools_and_runs_only_critical_addons(self):
        cluster = block(self.aks, 'resource "azurerm_kubernetes_cluster" "this"')
        default_pool = block(cluster, "default_node_pool {")
        self.assertIn("only_critical_addons_enabled = true", default_pool)
        self.assertIn('resource "azurerm_kubernetes_cluster_node_pool" "user"', self.aks)

    def test_node_pools_set_availability_zones(self):
        system_var = block((AKS / "variables.tf").read_text(), 'variable "system_node_pool"')
        self.assertIn('zones      = ["1", "2", "3"]', system_var)
        default_pool = block(self.aks, 'resource "azurerm_kubernetes_cluster" "this"')
        default_pool_body = block(default_pool, "default_node_pool {")
        self.assertIn("zones                        = var.system_node_pool.zones", default_pool_body)
        user_pool = block(self.aks, 'resource "azurerm_kubernetes_cluster_node_pool" "user"')
        self.assertIn("zones                 = each.value.zones", user_pool)

    def test_user_node_pools_support_spot_for_interruptible_workloads(self):
        pools_var = block((AKS / "variables.tf").read_text(), 'variable "user_node_pools"')
        self.assertIn("spot           = true", pools_var)
        user_pool = block(self.aks, 'resource "azurerm_kubernetes_cluster_node_pool" "user"')
        self.assertIn('priority        = each.value.spot ? "Spot" : "Regular"', user_pool)
        self.assertIn('eviction_policy = each.value.spot ? "Delete" : null', user_pool)

    def test_control_plane_identity_granted_network_contributor_on_route_table(self):
        role = block(self.aks, 'resource "azurerm_role_assignment" "control_plane_route_table"')
        self.assertIn("scope                = var.route_table_id", role)
        self.assertIn('role_definition_name = "Network Contributor"', role)

    # --- platform: private endpoints for ACR and Key Vault, RBAC ----------

    def test_acr_has_no_public_network_access(self):
        acr = block(self.platform, 'resource "azurerm_container_registry" "this"')
        self.assertIn("public_network_access_enabled = false", acr)
        self.assertIn('sku                           = "Premium"', acr)

    def test_key_vault_has_no_public_network_access_and_uses_rbac(self):
        kv = block(self.platform, 'resource "azurerm_key_vault" "this"')
        self.assertIn("public_network_access_enabled = false", kv)
        self.assertIn("rbac_authorization_enabled = true", kv)
        self.assertIn("purge_protection_enabled      = true", kv)

    def test_private_endpoints_exist_for_acr_and_key_vault(self):
        acr_pe = block(self.platform, 'resource "azurerm_private_endpoint" "acr"')
        self.assertIn('subresource_names              = ["registry"]', acr_pe)
        kv_pe = block(self.platform, 'resource "azurerm_private_endpoint" "key_vault"')
        self.assertIn('subresource_names              = ["vault"]', kv_pe)

    def test_platform_module_does_not_depend_on_aks_module_outputs(self):
        # Breaking this would create platform<->aks module cycle (platform
        # needs aks's kubelet/CSI identity; aks needs platform's Log
        # Analytics workspace). Those role assignments live in the example
        # root instead -- see terraform/examples/reference/main.tf.
        variables = (PLATFORM / "variables.tf").read_text()
        self.assertNotIn("kubelet_identity_object_id", variables)
        self.assertNotIn("key_vault_secrets_provider_object_id", variables)

    # --- workload identity: federated credential, no secret ----------------

    def test_pod_workload_identity_uses_federated_credential_not_a_secret(self):
        self.assertIn('resource "azurerm_federated_identity_credential" "workload"', self.workload_identity)
        cred = block(self.workload_identity, 'resource "azurerm_federated_identity_credential" "workload"')
        self.assertIn('audience            = ["api://AzureADTokenExchange"]', cred)
        self.assertIn(
            'subject             = "system:serviceaccount:${each.value.namespace}:${each.value.service_account_name}"',
            cred,
        )

    # --- pipeline identity: ADO federation, no client secret ---------------

    def test_ado_pipeline_uses_federated_credential_not_a_client_secret(self):
        self.assertIn(
            'resource "azuread_application_federated_identity_credential" "ado_pipeline"',
            self.pipeline_identity,
        )
        cred = block(
            self.pipeline_identity,
            'resource "azuread_application_federated_identity_credential" "ado_pipeline"',
        )
        self.assertIn('issuer         = "https://vstoken.dev.azure.com/${var.ado_organization}"', cred)
        self.assertNotRegex(self.pipeline_identity, r'resource\s+"azuread_application_password"')

    def test_ado_pipeline_identity_is_scoped_to_acr_push_only(self):
        role = block(self.pipeline_identity, 'resource "azurerm_role_assignment" "ado_pipeline_acr_push"')
        self.assertIn('role_definition_name = "AcrPush"', role)
        self.assertNotIn('role_definition_name = "Owner"', self.pipeline_identity)
        self.assertNotIn('role_definition_name = "Contributor"', self.pipeline_identity)

    # --- wiring in the reference example ------------------------------------

    def test_example_wires_every_module(self):
        for source in (
            '"../../modules/hub"',
            '"../../modules/spoke"',
            '"../../modules/aks"',
            '"../../modules/platform"',
            '"../../modules/workload-identity"',
            '"../../modules/pipeline-identity"',
        ):
            with self.subTest(source=source):
                self.assertIn(source, self.example)

    def test_example_sets_default_providers_without_credentials(self):
        providers = (EXAMPLE / "providers.tf").read_text()
        self.assertIn('provider "azurerm"', providers)
        self.assertIn('provider "azuread"', providers)
        self.assertNotRegex(providers, r"(?im)^\s*client_secret\s*=")

    def test_example_subscription_and_tenant_are_synthetic_placeholders(self):
        variables = (EXAMPLE / "variables.tf").read_text()
        self.assertIn('default     = "00000000-0000-0000-0000-000000000000"', variables)
        self.assertIn('default     = "11111111-1111-1111-1111-111111111111"', variables)

    def test_example_diagnostic_setting_sends_cluster_logs_to_log_analytics(self):
        diag = block(self.example, 'resource "azurerm_monitor_diagnostic_setting" "aks"')
        self.assertIn("log_analytics_workspace_id = module.platform.log_analytics_workspace_id", diag)
        self.assertIn('category = "kube-audit"', diag)


if __name__ == "__main__":
    unittest.main()
