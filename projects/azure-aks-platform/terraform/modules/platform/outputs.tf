output "acr_id" {
  description = "Container registry resource ID."
  value       = azurerm_container_registry.this.id
}

output "acr_login_server" {
  description = "Registry login server (e.g. example-platformacr.azurecr.io), only reachable from inside the spoke via the private endpoint."
  value       = azurerm_container_registry.this.login_server
}

output "key_vault_id" {
  description = "Key Vault resource ID."
  value       = azurerm_key_vault.this.id
}

output "key_vault_uri" {
  description = "Key Vault URI, referenced by the SecretProviderClass's keyvaultName/vaultUrl parameters."
  value       = azurerm_key_vault.this.vault_uri
}

output "log_analytics_workspace_id" {
  description = "Log Analytics workspace ID, consumed by the aks module's oms_agent block and by diagnostic settings."
  value       = azurerm_log_analytics_workspace.this.id
}
