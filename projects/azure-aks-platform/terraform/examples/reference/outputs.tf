output "cluster_name" {
  description = "AKS cluster name."
  value       = module.aks.cluster_name
}

output "oidc_issuer_url" {
  description = "Cluster OIDC issuer URL."
  value       = module.aks.oidc_issuer_url
}

output "acr_login_server" {
  description = "Container registry login server."
  value       = module.platform.acr_login_server
}

output "key_vault_uri" {
  description = "Key Vault URI."
  value       = module.platform.key_vault_uri
}

output "payments_api_workload_identity_client_id" {
  description = "Client ID the payments-api pod's ServiceAccount annotates with azure.workload.identity/client-id."
  value       = module.workload_identity.client_ids["payments-api"]
}

output "ado_pipeline_application_client_id" {
  description = "Client ID the Azure DevOps workload-identity-federation service connection is configured with."
  value       = module.pipeline_identity.application_client_id
}
