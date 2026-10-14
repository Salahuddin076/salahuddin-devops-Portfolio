# Cross-region (optionally cross-account) AWS Backup with immutability,
# alerting and native restore testing.
#
#   aws.primary  where protected resources live: primary vault, backup plans,
#                selections, the backup service role, Audit Manager.
#   aws.dr       the recovery region (or a separate recovery account): DR
#                vault, restore testing and its validator Lambda.
#
# Point aws.dr at another account (assume_role) and the module switches to
# cross-account mode: the DR vault and key also trust the primary account.

data "aws_caller_identity" "primary" {
  provider = aws.primary
}

data "aws_caller_identity" "dr" {
  provider = aws.dr
}

data "aws_partition" "current" {
  provider = aws.primary
}

data "aws_region" "primary" {
  provider = aws.primary
}

data "aws_region" "dr" {
  provider = aws.dr
}

locals {
  partition     = data.aws_partition.current.partition
  primary_acct  = data.aws_caller_identity.primary.account_id
  dr_acct       = data.aws_caller_identity.dr.account_id
  cross_account = local.primary_acct != local.dr_acct
  name_us       = replace(var.name_prefix, "-", "_")

  vault_lock = {
    enabled             = var.enable_vault_lock
    min_retention_days  = var.vault_lock_min_retention_days
    max_retention_days  = var.vault_lock_max_retention_days
    changeable_for_days = var.vault_lock_mode == "compliance" ? var.vault_lock_changeable_for_days : null
  }

  managed_policy_prefix = "arn:${local.partition}:iam::aws:policy"
  backup_managed_policies = {
    backup     = "${local.managed_policy_prefix}/service-role/AWSBackupServiceRolePolicyForBackup"
    restores   = "${local.managed_policy_prefix}/service-role/AWSBackupServiceRolePolicyForRestores"
    s3_backup  = "${local.managed_policy_prefix}/AWSBackupServiceRolePolicyForS3Backup"
    s3_restore = "${local.managed_policy_prefix}/AWSBackupServiceRolePolicyForS3Restore"
  }
  restore_managed_policies = {
    restores   = local.backup_managed_policies.restores
    s3_restore = local.backup_managed_policies.s3_restore
  }
}

# --------------------------------------------------------------------------
# Service roles. One in each account so cross-account mode needs no
# cross-account role trust: the primary role backs up and copies, the DR
# role runs restore tests.
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "backup_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["backup.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "backup" {
  provider = aws.primary

  name               = "${var.name_prefix}-backup-service"
  description        = "AWS Backup service role: backup, copy and restore for the ${var.name_prefix} plans."
  assume_role_policy = data.aws_iam_policy_document.backup_trust.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "backup" {
  provider = aws.primary
  for_each = local.backup_managed_policies

  role       = aws_iam_role.backup.name
  policy_arn = each.value
}

resource "aws_iam_role" "restore_testing" {
  provider = aws.dr

  name               = "${var.name_prefix}-restore-testing"
  description        = "AWS Backup role for restore testing against the ${var.name_prefix} DR vault."
  assume_role_policy = data.aws_iam_policy_document.backup_trust.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "restore_testing" {
  provider = aws.dr
  for_each = local.restore_managed_policies

  role       = aws_iam_role.restore_testing.name
  policy_arn = each.value
}

# --------------------------------------------------------------------------
# Vaults
# --------------------------------------------------------------------------

module "primary_vault" {
  source = "./modules/regional-vault"
  providers = {
    aws = aws.primary
  }

  vault_name               = "${var.name_prefix}-primary"
  vault_role               = "primary"
  backup_role_arns         = [aws_iam_role.backup.arn]
  break_glass_role_arn     = var.break_glass_role_arn
  kms_deletion_window_days = var.kms_deletion_window_days
  vault_lock               = local.vault_lock
  notification_events      = var.vault_notification_events
  notification_emails      = var.notification_emails
  enable_job_alarms        = var.enable_job_alarms
  tags                     = var.tags
}

module "dr_vault" {
  source = "./modules/regional-vault"
  providers = {
    aws = aws.dr
  }

  vault_name = "${var.name_prefix}-dr"
  vault_role = "dr"
  # The copy job runs as the primary backup role and re-encrypts into this
  # vault's key; restore tests run as the DR role and decrypt with it.
  backup_role_arns         = [aws_iam_role.backup.arn, aws_iam_role.restore_testing.arn]
  break_glass_role_arn     = var.break_glass_role_arn
  copy_source_account_ids  = local.cross_account ? [local.primary_acct] : []
  kms_deletion_window_days = var.kms_deletion_window_days
  vault_lock               = local.vault_lock
  notification_events      = var.vault_notification_events
  notification_emails      = var.notification_emails
  enable_job_alarms        = var.enable_job_alarms
  tags                     = var.tags
}
