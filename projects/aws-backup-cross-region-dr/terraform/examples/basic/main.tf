locals {
  # Single source of truth, also checked by scripts/check_plan_policy.py in CI.
  policy = jsondecode(file("${path.module}/../../../policy/backup-policy.json"))

  default_tags = {
    project    = var.project
    owner      = var.owner
    managed-by = "terraform"
  }
}

module "backup_dr" {
  source = "../../modules/backup-dr"
  providers = {
    aws.primary = aws.primary
    aws.dr      = aws.dr
  }

  name_prefix       = "backup-dr-demo"
  backup_plans      = local.policy.plans
  selection_tag_key = local.policy.selection_tag_key

  # Governance by default. Switching to compliance is a one-way door after
  # the grace period: read docs/decisions/0002 before changing the policy file.
  vault_lock_mode                = local.policy.vault_lock.mode
  vault_lock_min_retention_days  = local.policy.vault_lock.min_retention_days
  vault_lock_max_retention_days  = local.policy.vault_lock.max_retention_days
  vault_lock_changeable_for_days = local.policy.vault_lock.changeable_for_days

  break_glass_role_arn     = var.break_glass_role_arn
  enable_continuous_backup = true
  notification_emails      = var.notification_emails

  restore_testing = {
    schedule              = "cron(0 6 ? * SUN *)"
    selection_window_days = 7
    selections = {
      rds_gold = {
        resource_type              = "RDS"
        validation_window_hours    = 4
        restore_metadata_overrides = { dbsubnetgroupname = var.rds_test_subnet_group }
      }
      dynamodb_gold = { resource_type = "DynamoDB" }
      s3_gold       = { resource_type = "S3", validation_window_hours = 6 }
      ebs_silver    = { resource_type = "EBS", tier = "silver", validation_window_hours = 2 }
    }
  }

  restore_validator = {
    dynamodb_min_items = 100
    s3_min_objects     = 10
    s3_checksum_sample = 5
  }

  audit_framework = {
    enabled                 = var.enable_audit_framework
    required_retention_days = local.policy.retention_minimums_days.gold.daily
  }

  tags = {
    cost-center = "platform-resilience"
  }
}
