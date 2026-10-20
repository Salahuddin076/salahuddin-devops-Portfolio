output "aws_role_arn" {
  description = "Feeds the EKS values overlay's serviceAccount.annotations['eks.amazonaws.com/role-arn']."
  value       = aws_iam_role.portable_service.arn
}

output "azure_client_id" {
  description = "Feeds the AKS values overlay's serviceAccount.annotations['azure.workload.identity/client-id']."
  value       = azurerm_user_assigned_identity.portable_service.client_id
}

output "gcp_service_account_email" {
  description = "Feeds the GKE values overlay's serviceAccount.annotations['iam.gke.io/gcp-service-account']."
  value       = google_service_account.portable_service.email
}
