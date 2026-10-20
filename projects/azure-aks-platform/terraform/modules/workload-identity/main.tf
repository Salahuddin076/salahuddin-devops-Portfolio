# Microsoft Entra Workload ID for pods: one user-assigned managed identity
# per workload, federated to the cluster's OIDC issuer for exactly one
# namespace/ServiceAccount pair. A pod authenticates by presenting its
# projected Kubernetes service-account token to Entra ID, which exchanges
# it for an Entra token *because* a federated credential here says "trust
# this exact subject from this exact issuer" -- there is no client secret,
# no certificate, and nothing for a pod image or a CI log to leak.

resource "azurerm_user_assigned_identity" "workload" {
  for_each = var.workloads

  name                = "${each.key}-workload-identity"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

resource "azurerm_federated_identity_credential" "workload" {
  for_each = var.workloads

  name                = "${each.key}-federated-credential"
  resource_group_name = var.resource_group_name
  parent_id           = azurerm_user_assigned_identity.workload[each.key].id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = var.oidc_issuer_url
  subject             = "system:serviceaccount:${each.value.namespace}:${each.value.service_account_name}"
}
