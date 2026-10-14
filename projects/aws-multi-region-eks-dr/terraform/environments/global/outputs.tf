output "global_cluster_id" {
  description = "Aurora global cluster ID (the failover CLI's --confirm token)."
  value       = module.global_data.global_cluster_id
}

output "cluster_endpoints" {
  description = "Regional cluster endpoints for each region's values file."
  value       = module.global_data.cluster_endpoints
}

output "secret_arn" {
  description = "Database secret ARN (primary region)."
  value       = module.global_data.secret_arn
}

output "bucket_names" {
  description = "Application buckets by region."
  value       = module.global_data.bucket_names
}

output "failover_config" {
  description = "Input for config/failover.json."
  value       = module.global_data.failover_config
}
