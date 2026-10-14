# ElastiCache Valkey, one independent replication group per region. The cache
# holds sessions and read-through copies of data whose source of truth is
# Aurora, so after a failover the DR cache starts cold and refills. No global
# datastore: see docs/decisions/0003-valkey-rebuildable.md.

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name}-valkey"
  subnet_ids = [for s in aws_subnet.data : s.id]
  tags       = var.tags
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${var.name}-valkey"
  description          = "${var.name} rebuildable cache (${var.role} region)"

  engine               = "valkey"
  engine_version       = var.cache_engine_version
  node_type            = var.cache_node_type
  num_cache_clusters   = var.cache_nodes
  parameter_group_name = "default.valkey${split(".", var.cache_engine_version)[0]}"
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.cache.id]

  automatic_failover_enabled = var.cache_nodes > 1
  multi_az_enabled           = var.cache_nodes > 1

  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.this.arn
  transit_encryption_enabled = true
  transit_encryption_mode    = "required"

  # Rebuildable by design: no snapshots to restore from, nothing to copy.
  snapshot_retention_limit = 0

  apply_immediately          = false
  auto_minor_version_upgrade = true
  maintenance_window         = "sun:05:00-sun:06:00"

  tags = merge(var.tags, { Name = "${var.name}-valkey" })
}
