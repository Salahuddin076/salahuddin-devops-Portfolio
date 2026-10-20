# Reference wiring of every module into one root so `terraform validate`
# can exercise the whole graph at once. In a real deployment, hub, spoke,
# cluster and platform each get their own state/backend -- see
# docs/decisions/0002-separate-state-per-root.md -- so that, e.g., a node
# pool change can never touch the hub firewall's state file.

resource "azurerm_resource_group" "hub" {
  name     = "${var.name_prefix}-hub-rg"
  location = var.location
}

resource "azurerm_resource_group" "spoke" {
  name     = "${var.name_prefix}-spoke-rg"
  location = var.location
}

module "hub" {
  source = "../../modules/hub"

  resource_group_name = azurerm_resource_group.hub.name
  location            = var.location
  name_prefix         = "${var.name_prefix}-hub"
}

module "spoke" {
  source = "../../modules/spoke"

  resource_group_name     = azurerm_resource_group.spoke.name
  location                = var.location
  name_prefix             = "${var.name_prefix}-spoke"
  hub_vnet_id             = module.hub.vnet_id
  hub_vnet_name           = module.hub.vnet_name
  hub_resource_group_name = azurerm_resource_group.hub.name
  firewall_private_ip     = module.hub.firewall_private_ip
}

module "platform" {
  source = "../../modules/platform"

  resource_group_name         = azurerm_resource_group.spoke.name
  location                    = var.location
  name_prefix                 = replace(var.name_prefix, "-", "")
  tenant_id                   = var.tenant_id
  vnet_id                     = module.spoke.vnet_id
  private_endpoints_subnet_id = module.spoke.private_endpoints_subnet_id
}

# AcrPull for the kubelet identity and Key Vault Secrets User for the CSI
# driver add-on's identity are granted here, not inside either module: the
# `platform` module's own `log_analytics_workspace_id` output feeds the
# `aks` module (Container Insights), so granting these from inside
# `platform` using `aks`'s outputs would make the two modules depend on
# each other -- a cycle `terraform validate` rejects outright.
resource "azurerm_role_assignment" "kubelet_acr_pull" {
  scope                = module.platform.acr_id
  role_definition_name = "AcrPull"
  principal_id         = module.aks.kubelet_identity_object_id
}

resource "azurerm_role_assignment" "csi_driver_secrets_user" {
  scope                = module.platform.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.aks.key_vault_secrets_provider_object_id
}

module "aks" {
  source = "../../modules/aks"

  resource_group_name        = azurerm_resource_group.spoke.name
  location                   = var.location
  cluster_name               = "${var.name_prefix}-aks"
  dns_prefix                 = replace(var.name_prefix, "-", "")
  tenant_id                  = var.tenant_id
  admin_group_object_ids     = var.admin_group_object_ids
  vnet_subnet_id             = module.spoke.aks_subnet_id
  route_table_id             = module.spoke.route_table_id
  log_analytics_workspace_id = module.platform.log_analytics_workspace_id
}

# Diagnostic settings: AKS control-plane logs (audit, API server, scheduler,
# cluster-autoscaler) and all metrics land in the same Log Analytics
# workspace the Container Insights add-on (oms_agent, inside the aks
# module) also uses -- one pane for "what the cluster did" and "what ran on
# it."
resource "azurerm_monitor_diagnostic_setting" "aks" {
  name                       = "${var.name_prefix}-aks-diagnostics"
  target_resource_id         = module.aks.cluster_id
  log_analytics_workspace_id = module.platform.log_analytics_workspace_id

  enabled_log {
    category = "kube-audit"
  }
  enabled_log {
    category = "kube-apiserver"
  }
  enabled_log {
    category = "guard"
  }

  enabled_metric {
    category = "AllMetrics"
  }
}

# Microsoft Entra Workload ID for an example application pod. Namespace and
# ServiceAccount name here must match the Helm chart's values
# (helm/keyvault-csi-demo/values.yaml: serviceAccount.name / namespace) --
# the federated credential's `subject` and the pod's ServiceAccount are the
# two sides of the same trust relationship, and both must agree exactly.
module "workload_identity" {
  source = "../../modules/workload-identity"

  resource_group_name = azurerm_resource_group.spoke.name
  location            = var.location
  oidc_issuer_url     = module.aks.oidc_issuer_url

  workloads = {
    payments-api = {
      namespace            = "payments"
      service_account_name = "payments-api"
    }
  }
}

resource "azurerm_role_assignment" "payments_api_secrets_user" {
  scope                = module.platform.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.workload_identity.principal_ids["payments-api"]
}

# Azure DevOps pipeline identity: federated credential only, no client
# secret, scoped to push images to this registry and nothing else.
module "pipeline_identity" {
  source = "../../modules/pipeline-identity"

  display_name              = "${var.name_prefix}-ado-pipeline"
  ado_organization          = var.ado_organization
  ado_project_id            = var.ado_project_id
  ado_service_connection_id = var.ado_service_connection_id
  acr_id                    = module.platform.acr_id
}
