# Microsoft Entra Workload ID: one user-assigned managed identity, federated
# to the AKS cluster's OIDC issuer for exactly one namespace/ServiceAccount
# subject. A pod authenticates by presenting its projected service-account
# token to Entra ID, which exchanges it for an Entra token because this
# federated credential says "trust this exact subject from this exact
# issuer" -- no client secret, no certificate, nothing for a pod image or a
# CI log to leak. Same pattern as azure-aks-platform's workload-identity
# module, narrowed to the one portable ServiceAccount this project cares
# about.

resource "azurerm_user_assigned_identity" "portable_service" {
  name                = "portable-service-workload-identity"
  resource_group_name = var.azure_resource_group_name
  location            = var.azure_location
  tags                = var.tags
}

resource "azurerm_federated_identity_credential" "portable_service" {
  name                = "portable-service-federated-credential"
  resource_group_name = var.azure_resource_group_name
  parent_id           = azurerm_user_assigned_identity.portable_service.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = var.azure_oidc_issuer_url
  subject             = "system:serviceaccount:${var.service_account_namespace}:${var.service_account_name}"
}
