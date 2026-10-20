output "aws_role_arn" {
  value = module.identity_bindings.aws_role_arn
}

output "azure_client_id" {
  value = module.identity_bindings.azure_client_id
}

output "gcp_service_account_email" {
  value = module.identity_bindings.gcp_service_account_email
}
