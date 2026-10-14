# The database secret lives in the primary region with a replica in the DR
# region (same name, re-encrypted with the DR key). The host is deliberately
# not in the secret: each region's app reads its own regional cluster endpoint
# from its values file, so the replicated secret is valid in both regions.
#
# After an unplanned failover the replica can be promoted to a standalone
# secret (`aws secretsmanager stop-replication-to-replica`) so it can be
# rotated while the primary region is down. See runbooks/unplanned-failover.md.

resource "aws_secretsmanager_secret" "db" {
  provider = aws.primary

  name                    = var.secret_name
  description             = "Aurora master credentials for ${aws_rds_global_cluster.this.id} (no host: region-neutral)"
  kms_key_id              = var.primary.kms_key_arn
  recovery_window_in_days = 30

  replica {
    region     = local.dr_region
    kms_key_id = var.dr.kms_key_arn
  }

  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "db" {
  provider = aws.primary

  secret_id = aws_secretsmanager_secret.db.id
  secret_string_wo = jsonencode({
    engine   = "postgres"
    username = var.master_username
    password = ephemeral.aws_secretsmanager_random_password.db.random_password
    dbname   = var.database_name
    port     = 5432
  })
  secret_string_wo_version = var.db_password_version
}
