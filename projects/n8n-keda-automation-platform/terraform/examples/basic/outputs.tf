output "chart_values" {
  description = "Values to pass to helm/n8n-platform (database.host, redis.host, securityGroupsForPods.groupIds)."
  value = {
    database_host      = module.n8n_platform.db_endpoint
    redis_host         = module.n8n_platform.redis_primary_endpoint
    pod_security_group = module.n8n_platform.pod_security_group_id
  }
}

output "secret_arns" {
  description = "Secrets to fill out of band before installing the chart."
  value       = module.n8n_platform.secret_arns
}
