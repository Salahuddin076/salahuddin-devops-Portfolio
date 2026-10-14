# Aurora PostgreSQL Global Database: one writer cluster in the primary region,
# one read-only secondary in the DR region, storage-level replication between
# them (typically under a second of lag; measured, not assumed: see the lag
# alarm below and `failover status`).
#
# After a failover the roles are no longer what this file says:
#  - planned (switchover): the clusters swap roles inside the same global
#    cluster. Terraform sees no diff that matters.
#  - unplanned (detach + promote): the DR cluster leaves the global cluster.
#    global_cluster_identifier is ignored below so the next apply doesn't try
#    to re-attach it; rebuilding the topology is a deliberate step in
#    runbooks/failback.md, including the state moves it needs.

data "aws_region" "primary" {
  provider = aws.primary
}

data "aws_region" "dr" {
  provider = aws.dr
}

locals {
  primary_region = data.aws_region.primary.region
  dr_region      = data.aws_region.dr.region
}

# Generated at apply time and never stored in state: write-only arguments on
# the cluster and the secret version both read this ephemeral value.
ephemeral "aws_secretsmanager_random_password" "db" {
  provider = aws.primary

  password_length     = 40
  exclude_punctuation = true
}

resource "aws_rds_global_cluster" "this" {
  provider = aws.primary

  global_cluster_identifier = "${var.name}-global"
  engine                    = "aurora-postgresql"
  engine_version            = var.aurora_engine_version
  database_name             = var.database_name
  storage_encrypted         = true
  deletion_protection       = var.deletion_protection
}

resource "aws_rds_cluster" "primary" {
  provider = aws.primary

  cluster_identifier        = "${var.name}-${local.primary_region}"
  global_cluster_identifier = aws_rds_global_cluster.this.id
  engine                    = aws_rds_global_cluster.this.engine
  engine_version            = aws_rds_global_cluster.this.engine_version
  database_name             = var.database_name

  master_username            = var.master_username
  master_password_wo         = ephemeral.aws_secretsmanager_random_password.db.random_password
  master_password_wo_version = var.db_password_version

  storage_encrypted = true
  kms_key_id        = var.primary.kms_key_arn

  db_subnet_group_name   = var.primary.db_subnet_group_name
  vpc_security_group_ids = [var.primary.db_security_group_id]

  backup_retention_period             = var.backup_retention_days
  preferred_backup_window             = "03:00-04:00"
  copy_tags_to_snapshot               = true
  deletion_protection                 = var.deletion_protection
  final_snapshot_identifier           = "${var.name}-${local.primary_region}-final"
  iam_database_authentication_enabled = true
  enabled_cloudwatch_logs_exports     = ["postgresql"]

  tags = merge(var.tags, { Name = "${var.name}-${local.primary_region}" })

  lifecycle {
    ignore_changes = [global_cluster_identifier]
  }
}

resource "aws_rds_cluster_instance" "primary" {
  provider = aws.primary
  count    = var.primary_instance_count

  identifier           = "${var.name}-${local.primary_region}-${count.index + 1}"
  cluster_identifier   = aws_rds_cluster.primary.id
  engine               = aws_rds_cluster.primary.engine
  engine_version       = aws_rds_cluster.primary.engine_version
  instance_class       = var.aurora_instance_class
  db_subnet_group_name = var.primary.db_subnet_group_name

  # Global Database needs the same minor version in every region; upgrades
  # are done on the global cluster, not per instance.
  auto_minor_version_upgrade = false

  performance_insights_enabled    = true
  performance_insights_kms_key_id = var.primary.kms_key_arn

  tags = var.tags
}

# The secondary has no credentials of its own: it inherits users from the
# primary through storage replication.
resource "aws_rds_cluster" "dr" {
  provider = aws.dr

  cluster_identifier        = "${var.name}-${local.dr_region}"
  global_cluster_identifier = aws_rds_global_cluster.this.id
  engine                    = aws_rds_global_cluster.this.engine
  engine_version            = aws_rds_global_cluster.this.engine_version

  storage_encrypted = true
  kms_key_id        = var.dr.kms_key_arn

  db_subnet_group_name   = var.dr.db_subnet_group_name
  vpc_security_group_ids = [var.dr.db_security_group_id]

  backup_retention_period             = var.backup_retention_days
  preferred_backup_window             = "03:00-04:00"
  copy_tags_to_snapshot               = true
  deletion_protection                 = var.deletion_protection
  final_snapshot_identifier           = "${var.name}-${local.dr_region}-final"
  iam_database_authentication_enabled = true
  enabled_cloudwatch_logs_exports     = ["postgresql"]

  tags = merge(var.tags, { Name = "${var.name}-${local.dr_region}" })

  lifecycle {
    ignore_changes = [global_cluster_identifier, replication_source_identifier]
  }

  # The secondary can only join once the primary has a writer instance.
  depends_on = [aws_rds_cluster_instance.primary]
}

resource "aws_rds_cluster_instance" "dr" {
  provider = aws.dr
  count    = var.dr_instance_count

  identifier           = "${var.name}-${local.dr_region}-${count.index + 1}"
  cluster_identifier   = aws_rds_cluster.dr.id
  engine               = aws_rds_cluster.dr.engine
  engine_version       = aws_rds_cluster.dr.engine_version
  instance_class       = var.aurora_instance_class
  db_subnet_group_name = var.dr.db_subnet_group_name

  auto_minor_version_upgrade = false

  performance_insights_enabled    = true
  performance_insights_kms_key_id = var.dr.kms_key_arn

  tags = var.tags
}

# Lag is published by the secondary cluster, in the DR region, in milliseconds.
resource "aws_cloudwatch_metric_alarm" "replication_lag" {
  provider = aws.dr

  alarm_name          = "${var.name}-aurora-global-replication-lag"
  alarm_description   = "Aurora Global Database lag to ${local.dr_region} above ${var.replication_lag_alarm_seconds}s: planned failover is blocked and an unplanned one would lose more data."
  namespace           = "AWS/RDS"
  metric_name         = "AuroraGlobalDBReplicationLag"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = var.replication_lag_alarm_seconds * 1000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching"

  dimensions = {
    DBClusterIdentifier = aws_rds_cluster.dr.cluster_identifier
  }

  alarm_actions = var.alarm_topic_arns.dr
  ok_actions    = var.alarm_topic_arns.dr
  tags          = var.tags
}
