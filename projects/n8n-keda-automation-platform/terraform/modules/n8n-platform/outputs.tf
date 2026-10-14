output "redis_primary_endpoint" {
  description = "Chart value redis.host."
  value       = aws_elasticache_replication_group.queue.primary_endpoint_address
}

output "db_endpoint" {
  description = "Chart value database.host."
  value       = aws_db_instance.n8n.address
}

output "db_master_secret_arn" {
  description = "RDS-managed master secret (admin use only; n8n never reads it)."
  value       = aws_db_instance.n8n.master_user_secret[0].secret_arn
}

output "secret_arns" {
  description = "The three n8n secrets. Put their values out of band."
  value = {
    encryption_key = aws_secretsmanager_secret.encryption_key.arn
    db_app         = aws_secretsmanager_secret.db_app.arn
    redis_auth     = aws_secretsmanager_secret.redis_auth.arn
  }
}

output "pod_security_group_id" {
  description = "Chart value securityGroupsForPods.groupIds[0]."
  value       = aws_security_group.n8n_pods.id
}

output "n8n_role_arn" {
  description = "Pod Identity role for the n8n ServiceAccount."
  value       = aws_iam_role.n8n.arn
}

output "keda_role_arn" {
  description = "Pod Identity role for the KEDA operator."
  value       = aws_iam_role.keda.arn
}

output "kms_key_arn" {
  description = "CMK for the secrets, RDS and ElastiCache."
  value       = aws_kms_key.n8n.arn
}
