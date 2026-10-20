# Platform services: Azure Container Registry and Key Vault, both reachable
# from the cluster only through a private endpoint in the spoke, and Log
# Analytics as the single destination for cluster diagnostics. No resource
# in this module has a public data-plane endpoint.

data "azurerm_client_config" "current" {}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "${var.name_prefix}-law"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_analytics_retention_in_days
  tags                = var.tags
}

# Premium SKU is required for private endpoint support on ACR.
resource "azurerm_container_registry" "this" {
  # ACR names must be alphanumeric only (no hyphens), 5-50 chars.
  name                          = substr(replace("${var.name_prefix}acr", "-", ""), 0, 50)
  resource_group_name           = var.resource_group_name
  location                      = var.location
  sku                           = "Premium"
  admin_enabled                 = false
  public_network_access_enabled = false
  tags                          = var.tags
}

# AcrPull for the AKS kubelet identity and Key Vault Secrets User for the
# Key Vault Secrets Provider add-on's identity are granted from the example
# root (terraform/examples/reference/main.tf), not here -- both depend on
# the `aks` module's output, and this module's own `log_analytics_workspace_id`
# output feeds back into the `aks` module (Container Insights), so granting
# those role assignments here would make `platform` and `aks` depend on each
# other and create a module cycle `terraform validate` rejects outright.
resource "azurerm_key_vault" "this" {
  name                          = substr("${var.name_prefix}-kv", 0, 24)
  resource_group_name           = var.resource_group_name
  location                      = var.location
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  purge_protection_enabled      = true
  soft_delete_retention_days    = 90
  public_network_access_enabled = false

  # RBAC, not vault access policies: one authorization model (Azure RBAC)
  # for both the control plane (who can manage the vault) and the data
  # plane (who can read secrets), matching the cluster's own
  # azure_rbac_enabled=true instead of running two different models side
  # by side.
  rbac_authorization_enabled = true

  tags = var.tags
}

# --- Private DNS + private endpoints -----------------------------------

resource "azurerm_private_dns_zone" "acr" {
  name                = "privatelink.azurecr.io"
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_private_dns_zone" "key_vault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "acr" {
  name                  = "${var.name_prefix}-acr-link"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.acr.name
  virtual_network_id    = var.vnet_id
  registration_enabled  = false
}

resource "azurerm_private_dns_zone_virtual_network_link" "key_vault" {
  name                  = "${var.name_prefix}-kv-link"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.key_vault.name
  virtual_network_id    = var.vnet_id
  registration_enabled  = false
}

resource "azurerm_private_endpoint" "acr" {
  name                = "${var.name_prefix}-acr-pe"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.private_endpoints_subnet_id
  tags                = var.tags

  private_service_connection {
    name                           = "${var.name_prefix}-acr-psc"
    private_connection_resource_id = azurerm_container_registry.this.id
    subresource_names              = ["registry"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "acr-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.acr.id]
  }
}

resource "azurerm_private_endpoint" "key_vault" {
  name                = "${var.name_prefix}-kv-pe"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.private_endpoints_subnet_id
  tags                = var.tags

  private_service_connection {
    name                           = "${var.name_prefix}-kv-psc"
    private_connection_resource_id = azurerm_key_vault.this.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "kv-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.key_vault.id]
  }
}
