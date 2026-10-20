output "client_ids" {
  description = "Map of workload key -> managed identity client ID, for the pod ServiceAccount's azure.workload.identity/client-id annotation."
  value       = { for key, identity in azurerm_user_assigned_identity.workload : key => identity.client_id }
}

output "principal_ids" {
  description = "Map of workload key -> managed identity principal (object) ID, for downstream role assignments (e.g. Key Vault Secrets User)."
  value       = { for key, identity in azurerm_user_assigned_identity.workload : key => identity.principal_id }
}
