resource "aws_elasticache_subnet_group" "this" {
  name        = "${var.name}-queue"
  description = "${var.name} n8n queue"
  subnet_ids  = var.data_subnet_ids
  tags        = var.tags
}

# Cluster mode disabled on purpose: with cluster nodes n8n wraps the Bull
# prefix in a hash tag ({bull}:jobs:wait), and one small queue gains nothing
# from sharding.
resource "aws_elasticache_replication_group" "queue" {
  replication_group_id = "${var.name}-queue"
  description          = "${var.name} n8n Bull queue"

  engine               = "valkey"
  engine_version       = var.cache_engine_version
  node_type            = var.cache_node_type
  parameter_group_name = "default.valkey8"
  port                 = 6379

  num_cache_clusters         = var.cache_multi_az ? 2 : 1
  automatic_failover_enabled = var.cache_multi_az
  multi_az_enabled           = var.cache_multi_az

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.cache.id]

  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.n8n.arn
  transit_encryption_enabled = true
  transit_encryption_mode    = "required"

  # Write-only: read from Secrets Manager at apply time, never stored.
  auth_token_wo              = ephemeral.aws_secretsmanager_secret_version.redis_auth.secret_string
  auth_token_wo_version      = var.redis_auth_token_version
  auth_token_update_strategy = var.redis_auth_token_update_strategy

  snapshot_retention_limit   = var.cache_snapshot_retention_days
  snapshot_window            = "03:00-04:00"
  maintenance_window         = "sun:04:30-sun:05:30"
  auto_minor_version_upgrade = true
  apply_immediately          = false

  tags = var.tags
}
