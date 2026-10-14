resource "aws_cloudwatch_event_bus" "orders" {
  name = "${var.name_prefix}-orders"
  tags = var.tags
}

resource "aws_cloudwatch_event_rule" "order_accepted" {
  name           = "${var.name_prefix}-order-accepted"
  description    = "OrderAccepted domain events to the notifications topic."
  event_bus_name = aws_cloudwatch_event_bus.orders.name

  event_pattern = jsonencode({
    source        = [local.event_source]
    "detail-type" = ["OrderAccepted"]
  })

  tags = var.tags
}

resource "aws_cloudwatch_event_target" "notifications" {
  rule           = aws_cloudwatch_event_rule.order_accepted.name
  event_bus_name = aws_cloudwatch_event_bus.orders.name
  target_id      = "notifications-topic"
  arn            = aws_sns_topic.notifications.arn

  # A short human-readable notification instead of the raw event envelope.
  input_transformer {
    input_paths = {
      orderId       = "$.detail.data.orderId"
      totalCents    = "$.detail.data.totalCents"
      currency      = "$.detail.data.currency"
      correlationId = "$.detail.metadata.correlationId"
    }
    input_template = "\"Order <orderId> accepted: <totalCents> <currency> cents (correlation <correlationId>).\""
  }

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 24
  }
}

# --------------------------------------------------------------------------
# SNS topics, encrypted with a customer managed key. The AWS managed
# alias/aws/sns key cannot be used here: its key policy can't be changed to
# let EventBridge or CloudWatch encrypt messages.
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "sns_key" {
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
    sid       = "AllowServicePublishersToEncrypt"
    actions   = ["kms:GenerateDataKey*", "kms:Decrypt"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com", "cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_kms_key" "sns" {
  description             = "${var.name_prefix} SNS topic encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.sns_key.json
  tags                    = var.tags
}

resource "aws_kms_alias" "sns" {
  name          = "alias/${var.name_prefix}-sns"
  target_key_id = aws_kms_key.sns.key_id
}

resource "aws_sns_topic" "notifications" {
  name              = "${var.name_prefix}-order-notifications"
  kms_master_key_id = aws_kms_key.sns.arn
  tags              = var.tags
}

resource "aws_sns_topic" "alarms" {
  name              = "${var.name_prefix}-alarms"
  kms_master_key_id = aws_kms_key.sns.arn
  tags              = var.tags
}

data "aws_iam_policy_document" "notifications_topic" {
  statement {
    sid       = "AccountOwnerManagement"
    actions   = ["sns:GetTopicAttributes", "sns:SetTopicAttributes", "sns:Subscribe", "sns:ListSubscriptionsByTopic", "sns:Publish"]
    resources = [aws_sns_topic.notifications.arn]

    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }

  statement {
    sid       = "AllowOrderAcceptedRuleToPublish"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.notifications.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    # Only this one rule, not any rule in any account.
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.order_accepted.arn]
    }
  }

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.notifications.arn]

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

resource "aws_sns_topic_policy" "notifications" {
  arn    = aws_sns_topic.notifications.arn
  policy = data.aws_iam_policy_document.notifications_topic.json
}

data "aws_iam_policy_document" "alarms_topic" {
  statement {
    sid       = "AccountOwnerManagement"
    actions   = ["sns:GetTopicAttributes", "sns:SetTopicAttributes", "sns:Subscribe", "sns:ListSubscriptionsByTopic", "sns:Publish"]
    resources = [aws_sns_topic.alarms.arn]

    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }

  statement {
    sid       = "AllowThisStacksAlarmsToPublish"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alarms.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:cloudwatch:${local.region}:${local.account_id}:alarm:${var.name_prefix}-*"]
    }
  }
}

resource "aws_sns_topic_policy" "alarms" {
  arn    = aws_sns_topic.alarms.arn
  policy = data.aws_iam_policy_document.alarms_topic.json
}

resource "aws_sns_topic_subscription" "notification_email" {
  for_each  = toset(var.notification_emails)
  topic_arn = aws_sns_topic.notifications.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_sns_topic_subscription" "alarm_email" {
  for_each  = toset(var.alarm_emails)
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = each.value
}
