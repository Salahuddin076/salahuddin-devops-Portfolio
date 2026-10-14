output "organization_id" {
  description = "Organization ID."
  value       = module.organization.organization_id
}

output "organization_arn" {
  description = "Organization ARN (input to the shared-services environment)."
  value       = module.organization.organization_arn
}

output "ou_ids" {
  description = "OU key -> ID."
  value       = module.organization.ou_ids
}

output "account_ids" {
  description = "Account key -> ID."
  value       = module.organization.account_ids
}

output "scp_sizes" {
  description = "SCP name -> minified size (limit 5,120)."
  value       = module.guardrails.scp_sizes
}

output "log_bucket_name" {
  description = "Central log bucket."
  value       = module.log_archive.bucket_name
}

output "org_trail_arn" {
  description = "Organization trail ARN."
  value       = module.log_archive.trail_arn
}
