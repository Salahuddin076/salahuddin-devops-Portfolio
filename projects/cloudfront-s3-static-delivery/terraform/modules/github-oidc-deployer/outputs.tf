output "role_arn" {
  description = "Deploy role ARN. Store it as the repository variable the workflow reads (role-to-assume); it is not a secret."
  value       = aws_iam_role.deploy.arn
}

output "role_name" {
  description = "Deploy role name."
  value       = aws_iam_role.deploy.name
}

output "oidc_provider_arn" {
  description = "The GitHub OIDC provider in use (created here or passed in)."
  value       = local.oidc_provider_arn
}

output "allowed_subjects" {
  description = "Exact token.actions.githubusercontent.com:sub values the trust policy accepts."
  value       = local.allowed_subjects
}
