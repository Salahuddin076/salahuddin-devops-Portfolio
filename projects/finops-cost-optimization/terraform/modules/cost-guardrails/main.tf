data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  # Account id is resolved at plan time; nothing account-specific is hard-coded.
  export_bucket_name = "${var.name_prefix}-billing-exports-${local.account_id}"
  export_name        = "${var.name_prefix}-focus-1-0"
}

# ---------------------------------------------------------------------------
# KMS key for the alerts topic. The AWS-managed SNS key cannot be used here
# because its key policy does not let AWS Budgets / Cost Anomaly Detection
# publish, so a customer-managed key with a scoped policy is required.
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "alerts_kms" {
  statement {
    sid       = "AccountAdministration"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }

  statement {
    sid       = "AllowCostServicesToPublish"
    actions   = ["kms:GenerateDataKey*", "kms:Decrypt"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com", "costalerts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_kms_key" "alerts" {
  description             = "${var.name_prefix} cost alerts SNS encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.alerts_kms.json
  tags                    = var.tags
}

resource "aws_kms_alias" "alerts" {
  name          = "alias/${var.name_prefix}-cost-alerts"
  target_key_id = aws_kms_key.alerts.key_id
}

# ---------------------------------------------------------------------------
# SNS topic shared by budget and anomaly notifications
# ---------------------------------------------------------------------------
resource "aws_sns_topic" "alerts" {
  name              = "${var.name_prefix}-cost-alerts"
  kms_master_key_id = aws_kms_key.alerts.arn
  tags              = var.tags
}

data "aws_iam_policy_document" "alerts_topic" {
  statement {
    sid       = "AllowCostServicesPublish"
    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.alerts.arn]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com", "costalerts.amazonaws.com"]
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
    resources = [aws_sns_topic.alerts.arn]

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

resource "aws_sns_topic_policy" "alerts" {
  arn    = aws_sns_topic.alerts.arn
  policy = data.aws_iam_policy_document.alerts_topic.json
}

resource "aws_sns_topic_subscription" "email" {
  for_each = toset(var.notification_emails)

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = each.value
}
