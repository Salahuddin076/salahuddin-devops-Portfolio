# Private AKS cluster: no public API server endpoint, no local (static
# username/password or client-cert) Kubernetes accounts, Azure RBAC for
# Kubernetes Authorization tied to Entra ID groups instead, Azure Policy
# add-on for baseline pod security, and forced-tunneled egress (the spoke's
# route table, not this module, does the tunneling -- this module only
# needs `outbound_type = "userDefinedRouting"` so AKS doesn't try to attach
# its own load balancer outbound rule or NAT gateway on top of it).

# AKS needs its own identity to manage the UDR'd subnet (userDefinedRouting
# requires the cluster identity to hold Network Contributor on the route
# table/subnet, since AKS can no longer manage its own default route).
resource "azurerm_user_assigned_identity" "control_plane" {
  name                = "${var.cluster_name}-identity"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

resource "azurerm_role_assignment" "control_plane_route_table" {
  scope                = var.route_table_id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.control_plane.principal_id
}

resource "azurerm_kubernetes_cluster" "this" {
  name                = var.cluster_name
  resource_group_name = var.resource_group_name
  location            = var.location
  dns_prefix          = var.dns_prefix
  kubernetes_version  = var.kubernetes_version

  sku_tier = "Standard"

  private_cluster_enabled             = true
  private_dns_zone_id                 = "System"
  private_cluster_public_fqdn_enabled = false

  # No local accounts: every `kubectl` session authenticates as an Entra
  # identity, authorized by Azure RBAC below -- `az aks get-credentials`
  # against this cluster cannot fall back to a static client certificate.
  local_account_disabled = true

  # AKS-managed Entra integration is the only mode the azurerm provider
  # still supports (the legacy, self-managed `managed = false` mode was
  # removed from this block in the provider's v4 line) -- this block is
  # always the managed-AAD-integration shape.
  azure_active_directory_role_based_access_control {
    azure_rbac_enabled     = true
    admin_group_object_ids = var.admin_group_object_ids
    tenant_id              = var.tenant_id
  }

  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  key_vault_secrets_provider {
    secret_rotation_enabled  = true
    secret_rotation_interval = "2m"
  }

  azure_policy_enabled = true

  oms_agent {
    log_analytics_workspace_id = var.log_analytics_workspace_id
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.control_plane.id]
  }

  depends_on = [azurerm_role_assignment.control_plane_route_table]

  default_node_pool {
    name                         = "system"
    vm_size                      = var.system_node_pool.vm_size
    node_count                   = var.system_node_pool.node_count
    min_count                    = var.system_node_pool.min_count
    max_count                    = var.system_node_pool.max_count
    auto_scaling_enabled         = true
    zones                        = var.system_node_pool.zones
    vnet_subnet_id               = var.vnet_subnet_id
    only_critical_addons_enabled = true
    temporary_name_for_rotation  = "systemtmp"
  }

  network_profile {
    network_plugin    = "azure"
    network_policy    = "azure"
    outbound_type     = "userDefinedRouting"
    load_balancer_sku = "standard"
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [kubernetes_version]
  }
}

# Separate, scalable user node pools. Kept out of default_node_pool so the
# system pool (critical add-ons only) never competes for capacity with
# application workloads, and so a user pool's VM size/taints can change
# without forcing a cluster replace the way editing default_node_pool would.
resource "azurerm_kubernetes_cluster_node_pool" "user" {
  for_each = var.user_node_pools

  name                  = substr(each.key, 0, 12)
  kubernetes_cluster_id = azurerm_kubernetes_cluster.this.id
  vm_size               = each.value.vm_size
  node_count            = each.value.node_count
  min_count             = each.value.min_count
  max_count             = each.value.max_count
  auto_scaling_enabled  = true
  zones                 = each.value.zones
  vnet_subnet_id        = var.vnet_subnet_id
  mode                  = "User"
  node_taints           = each.value.node_taints
  node_labels           = each.value.node_labels

  priority        = each.value.spot ? "Spot" : "Regular"
  eviction_policy = each.value.spot ? "Delete" : null
  spot_max_price  = each.value.spot ? each.value.spot_max_price : null

  tags = var.tags
}
