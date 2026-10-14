data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.region

  tags = merge(var.tags, { component = "detective-response" })

  guardduty_paths = {
    severity = "$.detail.severity"
    type     = "$.detail.type"
    account  = "$.detail.accountId"
    region   = "$.region"
    id       = "$.detail.id"
  }

  securityhub_paths = {
    severity = "$.detail.findings[0].Severity.Label"
    title    = "$.detail.findings[0].Title"
    account  = "$.detail.findings[0].AwsAccountId"
    region   = "$.detail.findings[0].Region"
    product  = "$.detail.findings[0].ProductName"
    id       = "$.detail.findings[0].Id"
  }

  # One EventBridge rule per route. Low GuardDuty findings (< ticket
  # threshold) and Security Hub MEDIUM/LOW/INFORMATIONAL match nothing and
  # stay in the consoles for periodic review.
  routes = {
    guardduty-page = {
      description = "GuardDuty findings with severity >= ${var.guardduty_page_min_severity}: page the on-call responder."
      topic       = "page"
      pattern = {
        source        = ["aws.guardduty"]
        "detail-type" = ["GuardDuty Finding"]
        detail = {
          severity = [{ numeric = [">=", var.guardduty_page_min_severity] }]
        }
      }
      input_paths    = local.guardduty_paths
      input_template = "\"[PAGE] GuardDuty severity <severity> <type> in <account>/<region>. Finding <id>. Runbook: docs/operations.md, Triage a GuardDuty finding.\""
    }

    guardduty-ticket = {
      description = "GuardDuty findings with ${var.guardduty_ticket_min_severity} <= severity < ${var.guardduty_page_min_severity}: open a ticket."
      topic       = "ticket"
      pattern = {
        source        = ["aws.guardduty"]
        "detail-type" = ["GuardDuty Finding"]
        detail = {
          severity = [{ numeric = [">=", var.guardduty_ticket_min_severity, "<", var.guardduty_page_min_severity] }]
        }
      }
      input_paths    = local.guardduty_paths
      input_template = "\"[TICKET] GuardDuty severity <severity> <type> in <account>/<region>. Finding <id>.\""
    }

    # GuardDuty also forwards its findings into Security Hub; excluding that
    # product here stops every GuardDuty finding from alerting twice.
    securityhub-critical = {
      description = "New, active Security Hub findings labelled CRITICAL (excluding GuardDuty): page."
      topic       = "page"
      pattern = {
        source        = ["aws.securityhub"]
        "detail-type" = ["Security Hub Findings - Imported"]
        detail = {
          findings = {
            Severity    = { Label = ["CRITICAL"] }
            Workflow    = { Status = ["NEW"] }
            RecordState = ["ACTIVE"]
            ProductName = [{ "anything-but" = ["GuardDuty"] }]
          }
        }
      }
      input_paths    = local.securityhub_paths
      input_template = "\"[PAGE] Security Hub <severity> (<product>) <title> in <account>/<region>. Finding <id>.\""
    }

    securityhub-high = {
      description = "New, active Security Hub findings labelled HIGH (excluding GuardDuty): open a ticket."
      topic       = "ticket"
      pattern = {
        source        = ["aws.securityhub"]
        "detail-type" = ["Security Hub Findings - Imported"]
        detail = {
          findings = {
            Severity    = { Label = ["HIGH"] }
            Workflow    = { Status = ["NEW"] }
            RecordState = ["ACTIVE"]
            ProductName = [{ "anything-but" = ["GuardDuty"] }]
          }
        }
      }
      input_paths    = local.securityhub_paths
      input_template = "\"[TICKET] Security Hub <severity> (<product>) <title> in <account>/<region>. Finding <id>.\""
    }
  }

  topic_arns = {
    page   = aws_sns_topic.page.arn
    ticket = aws_sns_topic.ticket.arn
  }
}

# ----------------------------------------------------------------------------- detectors

resource "aws_guardduty_detector" "this" {
  count = var.enable_guardduty ? 1 : 0

  enable                       = true
  finding_publishing_frequency = var.guardduty_finding_publishing_frequency
  tags                         = local.tags
}

resource "aws_securityhub_account" "this" {
  count = var.enable_security_hub ? 1 : 0

  # Subscribe explicitly below instead of taking whatever the default set is.
  enable_default_standards = false
  auto_enable_controls     = true
}

resource "aws_securityhub_standards_subscription" "fsbp" {
  count = var.enable_security_hub ? 1 : 0

  standards_arn = "arn:${local.partition}:securityhub:${local.region}::standards/aws-foundational-security-best-practices/v/1.0.0"

  depends_on = [aws_securityhub_account.this]
}

# ----------------------------------------------------------------------------- KMS for the topics

data "aws_iam_policy_document" "sns_key" {
  statement {
    sid       = "AccountAdministration"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }

  # EventBridge (findings) and CloudWatch (the WAF alarm) publish to encrypted
  # topics; SNS needs these two calls on the publisher's behalf.
  statement {
    sid       = "AllowServicePublishersToUseKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey*"]
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
  description             = "${var.name_prefix} security notification topics"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.sns_key.json
  tags                    = local.tags
}

resource "aws_kms_alias" "sns" {
  name          = "alias/${var.name_prefix}-security-notifications"
  target_key_id = aws_kms_key.sns.key_id
}

# ----------------------------------------------------------------------------- topics

resource "aws_sns_topic" "page" {
  name              = "${var.name_prefix}-security-page"
  display_name      = "Security page"
  kms_master_key_id = aws_kms_key.sns.arn
  tags              = merge(local.tags, { route = "page" })
}

resource "aws_sns_topic" "ticket" {
  name              = "${var.name_prefix}-security-ticket"
  display_name      = "Security ticket"
  kms_master_key_id = aws_kms_key.sns.arn
  tags              = merge(local.tags, { route = "ticket" })
}

data "aws_iam_policy_document" "topic" {
  for_each = local.topic_arns

  statement {
    sid       = "AccountOwnerManage"
    effect    = "Allow"
    actions   = ["sns:GetTopicAttributes", "sns:SetTopicAttributes", "sns:Subscribe", "sns:ListSubscriptionsByTopic", "sns:Publish"]
    resources = [each.value]

    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }

  statement {
    sid       = "EventBridgeRulesPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [each.value]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [for k, r in aws_cloudwatch_event_rule.route : r.arn if local.routes[k].topic == each.key]
    }
  }

  statement {
    sid       = "CloudWatchAlarmsPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [each.value]

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
    actions   = ["sns:Publish"]
    resources = [each.value]

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

resource "aws_sns_topic_policy" "this" {
  for_each = local.topic_arns

  arn    = each.value
  policy = data.aws_iam_policy_document.topic[each.key].json
}

resource "aws_sns_topic_subscription" "page" {
  for_each = { for s in var.page_subscriptions : "${s.protocol}:${s.endpoint}" => s }

  topic_arn = aws_sns_topic.page.arn
  protocol  = each.value.protocol
  endpoint  = each.value.endpoint
}

resource "aws_sns_topic_subscription" "ticket" {
  for_each = { for s in var.ticket_subscriptions : "${s.protocol}:${s.endpoint}" => s }

  topic_arn = aws_sns_topic.ticket.arn
  protocol  = each.value.protocol
  endpoint  = each.value.endpoint
}

# ----------------------------------------------------------------------------- routing

resource "aws_cloudwatch_event_rule" "route" {
  for_each = local.routes

  name          = "${var.name_prefix}-${each.key}"
  description   = each.value.description
  event_pattern = jsonencode(each.value.pattern)
  tags          = merge(local.tags, { route = each.value.topic })

  lifecycle {
    precondition {
      condition     = var.guardduty_ticket_min_severity < var.guardduty_page_min_severity
      error_message = "guardduty_ticket_min_severity must be lower than guardduty_page_min_severity."
    }
  }
}

resource "aws_cloudwatch_event_target" "route" {
  for_each = local.routes

  rule      = aws_cloudwatch_event_rule.route[each.key].name
  target_id = "sns-${each.value.topic}"
  arn       = local.topic_arns[each.value.topic]

  input_transformer {
    input_paths    = each.value.input_paths
    input_template = each.value.input_template
  }

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 10
  }

  depends_on = [aws_sns_topic_policy.this]
}

# ----------------------------------------------------------------------------- secrets rotation (optional)

# Wiring only: the rotation function comes from the AWS-provided templates
# (docs/security.md explains why none is written here).
resource "aws_secretsmanager_secret_rotation" "this" {
  count = var.secret_rotation == null ? 0 : 1

  secret_id           = var.secret_rotation.secret_arn
  rotation_lambda_arn = var.secret_rotation.rotation_lambda_arn

  rotation_rules {
    automatically_after_days = var.secret_rotation.automatically_after_days
  }
}
