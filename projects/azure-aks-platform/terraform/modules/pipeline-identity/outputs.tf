output "application_client_id" {
  description = "App registration's client ID -- the value the Azure DevOps workload-identity-federation service connection is configured with."
  value       = azuread_application.ado_pipeline.client_id
}

output "service_principal_object_id" {
  description = "Service principal object ID backing the app registration."
  value       = azuread_service_principal.ado_pipeline.object_id
}
