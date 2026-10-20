"""Terraform invariants that `validate` can't express (no terraform binary needed)."""

from __future__ import annotations

import re
import unittest

from helpers import TERRAFORM_DIR

MODULES = TERRAFORM_DIR / "modules"
NETWORK = MODULES / "network"
GKE = MODULES / "gke-cluster"
CLOUD_SQL = MODULES / "cloud-sql"
SECRET_MANAGER = MODULES / "secret-manager"
DELIVERY = MODULES / "delivery"
PROJECT_APIS = MODULES / "project-apis"
EXAMPLE = TERRAFORM_DIR / "examples" / "reference"
ALL_ROOTS = (NETWORK, GKE, CLOUD_SQL, SECRET_MANAGER, DELIVERY, PROJECT_APIS, EXAMPLE)


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
        cls.network = tf(NETWORK)
        cls.gke = tf(GKE)
        cls.cloud_sql = tf(CLOUD_SQL)
        cls.secret_manager = tf(SECRET_MANAGER)
        cls.delivery = tf(DELIVERY)
        cls.project_apis = tf(PROJECT_APIS)
        cls.example = tf(EXAMPLE)
        cls.all = "\n".join([cls.network, cls.gke, cls.cloud_sql, cls.secret_manager,
                              cls.delivery, cls.project_apis, cls.example])

    # --- repo-wide hygiene ---------------------------------------------

    def test_versions_pin_google_provider_in_every_root(self):
        for root in ALL_ROOTS:
            with self.subTest(root=root.name):
                versions = (root / "versions.tf").read_text()
                self.assertIn('required_version = ">= 1.9.0"', versions)
                self.assertIn('version = ">= 6.0, < 7.0"', versions)

    def test_no_service_account_keys_anywhere(self):
        # The whole point of Workload Identity is that no JSON key file is
        # ever minted for a workload's identity. (Comments and docs mention
        # the resource type by name to explain why it's absent -- only an
        # actual `resource "google_service_account_key"` block would defeat
        # that, so match on the declaration, not the string.)
        self.assertNotRegex(self.all, r'resource\s+"google_service_account_key"')
        self.assertNotRegex(self.all, r"(?im)^\s*private_key\s*=")

    def test_no_credentials_or_hardcoded_secrets(self):
        self.assertNotRegex(self.all, r"(?i)client_secret|api_key\s*=\s*\"[A-Za-z0-9]{10,}")
        self.assertIn("CHANGE_ME_SYNTHETIC_PLACEHOLDER", self.example)

    def test_example_project_id_is_the_documented_synthetic_placeholder(self):
        project_id_var = block((EXAMPLE / "variables.tf").read_text(), 'variable "project_id"')
        self.assertIn('default     = "example-pharmacy-platform"', project_id_var)

    def test_every_variable_has_a_description(self):
        for root in ALL_ROOTS:
            variables_path = root / "variables.tf"
            if not variables_path.is_file():
                continue
            variables = variables_path.read_text()
            for name in re.findall(r'variable "([a-zA-Z_][a-zA-Z0-9_]*)"', variables):
                with self.subTest(root=root.name, variable=name):
                    self.assertIn("description", block(variables, f'variable "{name}"'))

    # --- network: private connectivity ----------------------------------

    def test_subnet_has_private_google_access_and_secondary_ranges(self):
        subnet = block(self.network, 'resource "google_compute_subnetwork" "primary"')
        self.assertIn("private_ip_google_access = true", subnet)
        self.assertIn('range_name    = "pods"', subnet)
        self.assertIn('range_name    = "services"', subnet)

    def test_private_service_access_peering_for_cloud_sql(self):
        self.assertIn('resource "google_compute_global_address" "private_service_access"', self.network)
        psa = block(self.network, 'resource "google_compute_global_address" "private_service_access"')
        self.assertIn('purpose       = "VPC_PEERING"', psa)
        self.assertIn('resource "google_service_networking_connection" "private_service_access"', self.network)

    def test_cloud_nat_is_optional_not_the_private_access_path(self):
        router = block((NETWORK / "variables.tf").read_text(), 'variable "enable_cloud_nat"')
        self.assertIn("default     = true", router)
        self.assertIn('count   = var.enable_cloud_nat ? 1 : 0', self.network)

    # --- GKE: private, regional, Workload Identity, two pools -----------

    def test_cluster_is_private_and_regional(self):
        cluster = block(self.gke, 'resource "google_container_cluster" "this"')
        self.assertIn("enable_private_nodes    = true", cluster)
        self.assertIn("location = var.region", cluster)
        self.assertIn('networking_mode = "VPC_NATIVE"', cluster)

    def test_workload_identity_enabled_on_cluster(self):
        cluster = block(self.gke, 'resource "google_container_cluster" "this"')
        self.assertIn('workload_pool = "${var.project_id}.svc.id.goog"', cluster)

    def test_workload_identity_binding_per_ksa_uses_full_namespace_ksa_member(self):
        binding = block(self.gke, 'resource "google_service_account_iam_member" "workload_identity"')
        self.assertIn('role', binding)
        self.assertIn('"roles/iam.workloadIdentityUser"', binding)
        self.assertIn(
            '"serviceAccount:${var.project_id}.svc.id.goog[${each.value.namespace}/${each.value.ksa_name}]"',
            binding,
        )
        self.assertIn("for_each = var.workload_identity_bindings", binding)

    def test_node_pools_use_gke_metadata_mode_for_workload_identity(self):
        self.assertIn('mode = "GKE_METADATA"', self.gke)

    def test_two_node_pools_parameterized_api_vs_ai_with_scale_to_zero(self):
        node_pools_var = block((GKE / "variables.tf").read_text(), 'variable "node_pools"')
        self.assertIn("map(object(", node_pools_var)
        example_pools = block(self.example, "node_pools = {")
        self.assertIn('workload     = "api"', example_pools)
        self.assertIn('workload     = "ai-inference"', example_pools)
        self.assertIn("min_count    = 0", example_pools)  # ai pool scales to zero
        self.assertIn("min_count    = 2", example_pools)  # api pool stays warm

    def test_ai_pool_is_tainted_so_only_ai_pods_schedule_there(self):
        example_pools = block(self.example, "node_pools = {")
        taint = block(example_pools, "taint = {")
        self.assertIn('key    = "workload"', taint)
        self.assertIn('effect = "NO_SCHEDULE"', taint)

    def test_master_authorized_networks_never_defaults_to_the_world(self):
        networks_var = block((GKE / "variables.tf").read_text(), 'variable "master_authorized_networks"')
        self.assertNotIn('cidr_block   = "0.0.0.0/0"', networks_var)
        self.assertIn('cidr_block   = "203.0.113.0/24"', networks_var)

    # --- Cloud SQL: private IP + HA --------------------------------------

    def test_cloud_sql_has_no_public_ip(self):
        instance = block(self.cloud_sql, 'resource "google_sql_database_instance" "this"')
        self.assertIn("ipv4_enabled    = false", instance)
        self.assertIn("private_network = var.network_id", instance)

    def test_cloud_sql_defaults_to_regional_ha(self):
        availability_var = block((CLOUD_SQL / "variables.tf").read_text(), 'variable "availability_type"')
        self.assertIn('default     = "REGIONAL"', availability_var)

    def test_cloud_sql_depends_on_the_private_service_connection(self):
        instance = block(self.cloud_sql, 'resource "google_sql_database_instance" "this"')
        self.assertIn("depends_on = [var.private_vpc_connection]", instance)

    def test_cloud_sql_password_is_generated_never_a_literal(self):
        self.assertIn('resource "random_password" "app_user"', self.cloud_sql)
        self.assertNotRegex(self.cloud_sql, r'password\s*=\s*"[^$][^"]*"')

    # --- Secret Manager: least-privilege per-secret access ---------------

    def test_secret_manager_grants_access_per_secret_not_project_wide(self):
        iam = block(self.secret_manager, 'resource "google_secret_manager_secret_iam_member" "accessor"')
        self.assertIn('role      = "roles/secretmanager.secretAccessor"', iam)
        self.assertIn("secret_id = google_secret_manager_secret.this[each.value.secret_key].secret_id", iam)

    def test_secret_manager_replication_is_user_managed_and_scoped(self):
        secret = block(self.secret_manager, 'resource "google_secret_manager_secret" "this"')
        self.assertIn("user_managed", secret)

    # --- Delivery: Artifact Registry scanning + audit logs ----------------

    def test_artifact_registry_has_immutable_tags(self):
        repo = block(self.delivery, 'resource "google_artifact_registry_repository" "images"')
        self.assertIn("immutable_tags = true", repo)

    def test_cloud_build_trigger_wired_to_a_branch(self):
        trigger = block(self.delivery, 'resource "google_cloudbuild_trigger" "build_and_push"')
        self.assertIn("branch = var.trigger_branch_pattern", trigger)

    def test_audit_logging_enabled_for_cloud_sql_and_secret_manager(self):
        sql_audit = block(self.delivery, 'resource "google_project_iam_audit_config" "cloud_sql"')
        self.assertIn('service = "cloudsql.googleapis.com"', sql_audit)
        self.assertIn('log_type = "DATA_READ"', sql_audit)
        self.assertIn('log_type = "DATA_WRITE"', sql_audit)

        secrets_audit = block(self.delivery, 'resource "google_project_iam_audit_config" "secret_manager"')
        self.assertIn('service = "secretmanager.googleapis.com"', secrets_audit)
        self.assertIn('log_type = "DATA_READ"', secrets_audit)
        self.assertIn('log_type = "DATA_WRITE"', secrets_audit)

    # --- wiring in the reference example ----------------------------------

    def test_example_wires_all_five_modules(self):
        for source in (
            '"../../modules/project-apis"',
            '"../../modules/network"',
            '"../../modules/gke-cluster"',
            '"../../modules/cloud-sql"',
            '"../../modules/secret-manager"',
            '"../../modules/delivery"',
        ):
            with self.subTest(source=source):
                self.assertIn(source, self.example)

    def test_example_sets_default_provider_without_credentials(self):
        providers = (EXAMPLE / "providers.tf").read_text()
        self.assertIn('provider "google"', providers)
        self.assertNotRegex(providers, r"(?m)^\s*credentials\s*=")


if __name__ == "__main__":
    unittest.main()
