resource "aws_db_subnet_group" "this" {
  name        = "${var.name}-db"
  description = "${var.name} n8n database"
  subnet_ids  = var.data_subnet_ids
  tags        = var.tags
}

resource "aws_db_parameter_group" "this" {
  name_prefix = "${var.name}-pg"
  family      = "postgres${split(".", var.db_engine_version)[0]}"
  description = "${var.name} n8n: TLS required"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "2000"
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = var.tags
}

# RDS PostgreSQL, single instance with a Multi-AZ standby (ADR 0004). The
# master password is generated and held by RDS in Secrets Manager
# (manage_master_user_password), so it never appears in config or state. n8n
# does not use the master user: it connects as an application role whose
# credentials are in var.db_app_secret_name.
resource "aws_db_instance" "n8n" {
  identifier     = "${var.name}-db"
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  db_name                       = "n8n"
  username                      = "n8n_admin"
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.n8n.arn

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.n8n.arn

  multi_az               = var.db_multi_az
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.this.name
  publicly_accessible    = false

  backup_retention_period   = var.db_backup_retention_days
  backup_window             = "02:00-03:00"
  maintenance_window        = "sun:05:30-sun:06:30"
  copy_tags_to_snapshot     = true
  delete_automated_backups  = false
  deletion_protection       = var.db_deletion_protection
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name}-db-final"

  auto_minor_version_upgrade      = true
  allow_major_version_upgrade     = false
  enabled_cloudwatch_logs_exports = ["postgresql"]

  performance_insights_enabled    = true
  performance_insights_kms_key_id = aws_kms_key.n8n.arn

  tags = var.tags
}
