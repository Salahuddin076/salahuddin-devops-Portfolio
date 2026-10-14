# One region's half of the design: a CMK-encrypted, locked vault whose access
# policy refuses early deletion, plus that region's alerting (an encrypted
# SNS topic, vault notifications, EventBridge rules and job-failure alarms).
# The parent module instantiates it twice, once per provider alias.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.region
  root_arn   = "arn:${local.partition}:iam::${local.account_id}:root"

  # Account-wide job failure events. Vault notifications only cover one
  # vault; these catch a job that failed before it ever reached a vault
  # (for example a KMS or IAM error on the source resource).
  job_failure_patterns = {
    backup-job-failed = {
      detail_type = "Backup Job State Change"
      detail      = { state = ["FAILED", "EXPIRED", "ABORTED"] }
    }
    copy-job-failed = {
      detail_type = "Copy Job State Change"
      detail      = { state = ["FAILED"] }
    }
    restore-job-failed = {
      detail_type = "Restore Job State Change"
      detail      = { status = ["FAILED"] }
    }
  }

  job_alarms = {
    backup-jobs-failed = "NumberOfBackupJobsFailed"
    copy-jobs-failed   = "NumberOfCopyJobsFailed"
  }
}

# --------------------------------------------------------------------------
# Vault key. Each region has its own key: a copy is re-encrypted with the
# destination vault's key, so losing or disabling one key never makes the
# other region's recovery points unreadable.
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "vault_key" {
  statement {
    sid       = "AccountAdministration"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = [local.root_arn]
    }
  }

  statement {
    sid = "BackupRolesUseKey"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = var.backup_role_arns
    }
  }

  statement {
    sid       = "BackupRolesGrantsForAwsResources"
    actions   = ["kms:CreateGrant", "kms:ListGrants", "kms:RevokeGrant"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = var.backup_role_arns
    }

    condition {
      test     = "Bool"
      variable = "kms:GrantIsForAWSResource"
      values   = ["true"]
    }
  }

  dynamic "statement" {
    for_each = length(var.copy_source_account_ids) > 0 ? [1] : []

    content {
      sid       = "CrossAccountCopySources"
      actions   = ["kms:Decrypt", "kms:GenerateDataKey*", "kms:DescribeKey", "kms:CreateGrant"]
      resources = ["*"]

      principals {
        type        = "AWS"
        identifiers = [for id in var.copy_source_account_ids : "arn:${local.partition}:iam::${id}:root"]
      }

      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = ["backup.${local.region}.amazonaws.com"]
      }
    }
  }
}

resource "aws_kms_key" "vault" {
  description             = "AWS Backup ${var.vault_role} vault key (${var.vault_name})"
  enable_key_rotation     = true
  deletion_window_in_days = var.kms_deletion_window_days
  policy                  = data.aws_iam_policy_document.vault_key.json
  tags                    = merge(var.tags, { vault-role = var.vault_role })
}

resource "aws_kms_alias" "vault" {
  name          = "alias/${var.vault_name}"
  target_key_id = aws_kms_key.vault.key_id
}

# --------------------------------------------------------------------------
# Vault, lock and access policy
# --------------------------------------------------------------------------

resource "aws_backup_vault" "this" {
  name          = var.vault_name
  kms_key_arn   = aws_kms_key.vault.arn
  force_destroy = false
  tags          = merge(var.tags, { vault-role = var.vault_role })
}

# Governance mode when changeable_for_days is null: users with
# backup:DeleteBackupVaultLockConfiguration can still remove the lock.
# Compliance mode when it is set: after that many days the lock is
# IMMUTABLE. Nobody, including the account root user and AWS Support, can
# remove it, shorten retention below the minimum, or delete the vault
# until every recovery point has aged out. See ADR 0002.
resource "aws_backup_vault_lock_configuration" "this" {
  count = var.vault_lock.enabled ? 1 : 0

  backup_vault_name   = aws_backup_vault.this.name
  min_retention_days  = var.vault_lock.min_retention_days
  max_retention_days  = var.vault_lock.max_retention_days
  changeable_for_days = var.vault_lock.changeable_for_days
}

data "aws_iam_policy_document" "vault_access" {
  statement {
    sid    = "DenyRecoveryPointDeletionExceptBreakGlass"
    effect = "Deny"
    actions = [
      "backup:DeleteRecoveryPoint",
      "backup:UpdateRecoveryPointLifecycle",
    ]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    condition {
      test     = "ArnNotEquals"
      variable = "aws:PrincipalArn"
      values   = [var.break_glass_role_arn]
    }
  }

  dynamic "statement" {
    for_each = length(var.copy_source_account_ids) > 0 ? [1] : []

    content {
      sid       = "AllowCrossAccountCopyIn"
      actions   = ["backup:CopyIntoBackupVault"]
      resources = ["*"]

      principals {
        type        = "AWS"
        identifiers = [for id in var.copy_source_account_ids : "arn:${local.partition}:iam::${id}:root"]
      }
    }
  }
}

resource "aws_backup_vault_policy" "this" {
  backup_vault_name = aws_backup_vault.this.name
  policy            = data.aws_iam_policy_document.vault_access.json
}

# --------------------------------------------------------------------------
# Notifications: an SNS topic on its own CMK. The key policy must let each
# publishing service generate data keys, or delivery fails silently.
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "notify_key" {
  statement {
    sid       = "AccountAdministration"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = [local.root_arn]
    }
  }

  statement {
    sid       = "PublishingServicesUseKey"
    actions   = ["kms:GenerateDataKey*", "kms:Decrypt"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["backup.amazonaws.com", "events.amazonaws.com", "cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_kms_key" "notify" {
  description             = "AWS Backup ${var.vault_role} notification topic key"
  enable_key_rotation     = true
  deletion_window_in_days = var.kms_deletion_window_days
  policy                  = data.aws_iam_policy_document.notify_key.json
  tags                    = var.tags
}

resource "aws_kms_alias" "notify" {
  name          = "alias/${var.vault_name}-notifications"
  target_key_id = aws_kms_key.notify.key_id
}

resource "aws_sns_topic" "notify" {
  name              = "${var.vault_name}-notifications"
  kms_master_key_id = aws_kms_key.notify.arn
  tags              = var.tags
}

data "aws_iam_policy_document" "topic" {
  statement {
    sid       = "BackupVaultNotifications"
    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.notify.arn]

    principals {
      type        = "Service"
      identifiers = ["backup.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }

  statement {
    sid       = "EventBridgeJobFailureRules"
    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.notify.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [for r in aws_cloudwatch_event_rule.job_failure : r.arn]
    }
  }

  statement {
    sid       = "CloudWatchAlarms"
    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.notify.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.notify.arn]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_sns_topic_policy" "notify" {
  arn    = aws_sns_topic.notify.arn
  policy = data.aws_iam_policy_document.topic.json
}

resource "aws_sns_topic_subscription" "email" {
  for_each = toset(var.notification_emails)

  topic_arn = aws_sns_topic.notify.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_backup_vault_notifications" "this" {
  backup_vault_name   = aws_backup_vault.this.name
  sns_topic_arn       = aws_sns_topic.notify.arn
  backup_vault_events = var.notification_events

  depends_on = [aws_sns_topic_policy.notify]
}

# --------------------------------------------------------------------------
# EventBridge: account-wide failed and expired jobs in this region
# --------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "job_failure" {
  for_each = local.job_failure_patterns

  name        = "${var.vault_name}-${each.key}"
  description = "AWS Backup ${each.value.detail_type} to a failure state, routed to ${aws_sns_topic.notify.name}."
  event_pattern = jsonencode({
    source        = ["aws.backup"]
    "detail-type" = [each.value.detail_type]
    detail        = each.value.detail
  })
  tags = var.tags
}

resource "aws_cloudwatch_event_target" "job_failure" {
  for_each = local.job_failure_patterns

  rule      = aws_cloudwatch_event_rule.job_failure[each.key].name
  target_id = "sns"
  arn       = aws_sns_topic.notify.arn

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 10
  }
}

# --------------------------------------------------------------------------
# CloudWatch alarms on the AWS/Backup job metrics (region-wide aggregate)
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "jobs_failed" {
  for_each = var.enable_job_alarms ? local.job_alarms : {}

  alarm_name          = "${var.vault_name}-${each.key}"
  alarm_description   = "One or more AWS Backup ${each.key} in ${local.region}. Runbook: docs/operations.md."
  namespace           = "AWS/Backup"
  metric_name         = each.value
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.notify.arn]
  ok_actions          = [aws_sns_topic.notify.arn]
  tags                = var.tags
}
