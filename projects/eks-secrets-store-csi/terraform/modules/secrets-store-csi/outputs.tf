output "db_secret_arn" {
  description = "ARN of the DB credential secret (put its JSON value out of band)."
  value       = aws_secretsmanager_secret.db.arn
}

output "api_key_secret_arn" {
  description = "ARN of the API key secret (put its value out of band)."
  value       = aws_secretsmanager_secret.api_key.arn
}

output "kms_key_arn" {
  description = "ARN of the CMK that encrypts both secrets."
  value       = aws_kms_key.secrets.arn
}

output "app_role_arn" {
  description = "IAM role the app's ServiceAccount assumes through Pod Identity."
  value       = aws_iam_role.app.arn
}

output "pod_identity_association_id" {
  description = "ID of the Pod Identity association for namespace/service_account."
  value       = aws_eks_pod_identity_association.app.association_id
}

output "csi_addon_version" {
  description = "Installed version of the aws-secrets-store-csi-driver-provider add-on."
  value       = aws_eks_addon.secrets_store_csi.addon_version
}

output "rotation_enabled" {
  description = "Whether managed rotation is configured for the DB secret."
  value       = var.rotation_lambda_arn != null
}

output "helm_values" {
  description = "Values for helm/secure-frontend that must agree with this module (pass with --set or a generated values file)."
  value = {
    "aws.region"                = data.aws_region.current.region
    "aws.usePodIdentity"        = true
    "serviceAccount.name"       = var.service_account
    "secrets.db.secretName"     = aws_secretsmanager_secret.db.name
    "secrets.apiKey.secretName" = aws_secretsmanager_secret.api_key.name
  }
}
