output "site_urls" {
  description = "HTTPS URLs of the site."
  value       = module.static_site.site_urls
}

output "bucket_name" {
  description = "Deploy target bucket (repository variable STATIC_SITE_BUCKET)."
  value       = module.static_site.bucket_name
}

output "distribution_id" {
  description = "Distribution to invalidate (repository variable STATIC_SITE_DISTRIBUTION_ID)."
  value       = module.static_site.distribution_id
}

output "distribution_domain_name" {
  description = "The *.cloudfront.net name."
  value       = module.static_site.distribution_domain_name
}

output "deploy_role_arn" {
  description = "Role for the workflow (repository variable STATIC_SITE_DEPLOY_ROLE_ARN)."
  value       = module.deployer.role_arn
}

output "allowed_subjects" {
  description = "OIDC sub values the deploy role trusts."
  value       = module.deployer.allowed_subjects
}

output "access_log_group_name" {
  description = "CloudFront access logs (us-east-1)."
  value       = module.static_site.access_log_group_name
}
