output "db_secret_arn" {
  description = "Put the DB credential JSON here out of band."
  value       = module.secrets_store_csi.db_secret_arn
}

output "api_key_secret_arn" {
  description = "Put the API key here out of band."
  value       = module.secrets_store_csi.api_key_secret_arn
}

output "app_role_arn" {
  description = "Role bound to web/secure-frontend through Pod Identity."
  value       = module.secrets_store_csi.app_role_arn
}

output "helm_values" {
  description = "Values the chart must use to match this stack."
  value       = module.secrets_store_csi.helm_values
}
