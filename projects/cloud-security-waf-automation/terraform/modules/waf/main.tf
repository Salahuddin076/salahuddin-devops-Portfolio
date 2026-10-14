data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.region

  web_acl_name = "${var.name_prefix}-web-acl"

  # AWS requires WAF log groups to be named aws-waf-logs-*.
  log_group_name = "aws-waf-logs-${var.name_prefix}"

  enabled_managed_groups = {
    for name, g in var.managed_rule_groups : name => g if g.enabled
  }

  # CloudFront metrics carry no Region dimension; regional ones do.
  alarm_dimensions = var.scope == "CLOUDFRONT" ? {
    WebACL = local.web_acl_name
    Rule   = "ALL"
    } : {
    WebACL = local.web_acl_name
    Rule   = "ALL"
    Region = local.region
  }

  tags = merge(var.tags, { component = "waf" })
}

# ----------------------------------------------------------------------------- IP sets

resource "aws_wafv2_ip_set" "allow" {
  count = length(var.allow_ip_cidrs) > 0 ? 1 : 0

  name               = "${var.name_prefix}-allow"
  description        = "Always-allowed client ranges (evaluated before every other rule)."
  scope              = var.scope
  ip_address_version = "IPV4"
  addresses          = var.allow_ip_cidrs
  tags               = local.tags
}

resource "aws_wafv2_ip_set" "block" {
  count = length(var.block_ip_cidrs) > 0 ? 1 : 0

  name               = "${var.name_prefix}-block"
  description        = "Blocked client ranges."
  scope              = var.scope
  ip_address_version = "IPV4"
  addresses          = var.block_ip_cidrs
  tags               = local.tags
}

# ----------------------------------------------------------------------------- web ACL

resource "aws_wafv2_web_acl" "this" {
  name        = local.web_acl_name
  description = "Edge protection for ${var.name_prefix}: IP lists, per-IP rate limit, AWS managed rule groups."
  scope       = var.scope

  default_action {
    allow {}
  }

  # Priority 0: allow list. Terminates with ALLOW, so later rules never see these clients.
  dynamic "rule" {
    for_each = aws_wafv2_ip_set.allow
    content {
      name     = "ip-allow-list"
      priority = 0

      action {
        allow {}
      }

      statement {
        ip_set_reference_statement {
          arn = rule.value.arn
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name_prefix}-ip-allow-list"
        sampled_requests_enabled   = true
      }
    }
  }

  # Priority 1: block list.
  dynamic "rule" {
    for_each = aws_wafv2_ip_set.block
    content {
      name     = "ip-block-list"
      priority = 1

      action {
        dynamic "block" {
          for_each = var.block_list_mode == "block" ? [1] : []
          content {}
        }
        dynamic "count" {
          for_each = var.block_list_mode == "count" ? [1] : []
          content {}
        }
      }

      statement {
        ip_set_reference_statement {
          arn = rule.value.arn
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name_prefix}-ip-block-list"
        sampled_requests_enabled   = true
      }
    }
  }

  # Priority 2: per-client-IP rate limit.
  dynamic "rule" {
    for_each = var.rate_limit == null ? [] : [var.rate_limit]
    content {
      name     = "rate-limit-per-ip"
      priority = 2

      action {
        dynamic "block" {
          for_each = var.rate_limit_mode == "block" ? [1] : []
          content {}
        }
        dynamic "count" {
          for_each = var.rate_limit_mode == "count" ? [1] : []
          content {}
        }
      }

      statement {
        rate_based_statement {
          limit                 = rule.value
          aggregate_key_type    = "IP"
          evaluation_window_sec = var.rate_limit_window_seconds
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name_prefix}-rate-limit-per-ip"
        sampled_requests_enabled   = true
      }
    }
  }

  # Priority 10+: AWS managed rule groups. "count" mode = override_action count:
  # matches are logged as nonTerminatingMatchingRules but nothing is blocked.
  dynamic "rule" {
    for_each = local.enabled_managed_groups
    content {
      name     = "AWS-${rule.key}"
      priority = rule.value.priority

      override_action {
        dynamic "none" {
          for_each = rule.value.mode == "block" ? [1] : []
          content {}
        }
        dynamic "count" {
          for_each = rule.value.mode == "count" ? [1] : []
          content {}
        }
      }

      statement {
        managed_rule_group_statement {
          name        = rule.key
          vendor_name = "AWS"

          # Exclusions: a rule with a confirmed false positive keeps matching
          # (and logging) but its action becomes COUNT.
          dynamic "rule_action_override" {
            for_each = toset(rule.value.rules_to_count)
            content {
              name = rule_action_override.value
              action_to_use {
                count {}
              }
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name_prefix}-${rule.key}"
        sampled_requests_enabled   = true
      }
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.name_prefix}-web-acl"
    sampled_requests_enabled   = true
  }

  tags = local.tags

  lifecycle {
    precondition {
      condition     = var.scope == "REGIONAL" || local.region == "us-east-1"
      error_message = "A CLOUDFRONT web ACL must be created with a provider configured for us-east-1."
    }

    precondition {
      condition     = length(distinct([for g in local.enabled_managed_groups : g.priority])) == length(local.enabled_managed_groups)
      error_message = "Enabled managed rule groups must have unique priorities."
    }
  }
}

# ----------------------------------------------------------------------------- logging

resource "aws_cloudwatch_log_group" "waf" {
  name              = local.log_group_name
  retention_in_days = var.log_retention_days
  kms_key_id        = var.log_kms_key_arn
  tags              = local.tags
}

# WAF delivers through the vended-logs service. AWS can add this policy itself
# when the caller has logs:PutResourcePolicy; declaring it keeps it reviewable.
data "aws_iam_policy_document" "waf_log_delivery" {
  statement {
    sid     = "AWSWAFLogDelivery"
    effect  = "Allow"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]

    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }

    resources = ["arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:aws-waf-logs-*:log-stream:*"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:logs:${local.region}:${local.account_id}:*"]
    }
  }
}

resource "aws_cloudwatch_log_resource_policy" "waf_log_delivery" {
  count = var.create_log_resource_policy ? 1 : 0

  policy_name     = "${var.name_prefix}-waf-log-delivery"
  policy_document = data.aws_iam_policy_document.waf_log_delivery.json
}

resource "aws_wafv2_web_acl_logging_configuration" "this" {
  resource_arn            = aws_wafv2_web_acl.this.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]

  # Credentials and session tokens never reach the logs.
  dynamic "redacted_fields" {
    for_each = toset(var.redacted_headers)
    content {
      single_header {
        name = redacted_fields.value
      }
    }
  }

  depends_on = [aws_cloudwatch_log_resource_policy.waf_log_delivery]
}

# ----------------------------------------------------------------------------- association

resource "aws_wafv2_web_acl_association" "alb" {
  count = var.associate_alb ? 1 : 0

  resource_arn = var.alb_arn
  web_acl_arn  = aws_wafv2_web_acl.this.arn

  lifecycle {
    precondition {
      condition     = var.scope == "REGIONAL"
      error_message = "Only a REGIONAL web ACL can be associated with an ALB; attach a CLOUDFRONT web ACL on the distribution instead."
    }

    precondition {
      condition     = var.alb_arn != null
      error_message = "associate_alb is true but alb_arn is not set."
    }
  }
}

# ----------------------------------------------------------------------------- alarm

resource "aws_cloudwatch_metric_alarm" "blocked_spike" {
  alarm_name          = "${var.name_prefix}-waf-blocked-requests-spike"
  alarm_description   = "Web ACL ${local.web_acl_name} blocked more than ${var.blocked_requests_alarm_threshold} requests in ${var.alarm_period_seconds}s: an attack, or a rule just flipped to block with false positives. See docs/operations.md."
  namespace           = "AWS/WAFV2"
  metric_name         = "BlockedRequests"
  dimensions          = local.alarm_dimensions
  statistic           = "Sum"
  period              = var.alarm_period_seconds
  evaluation_periods  = 1
  threshold           = var.blocked_requests_alarm_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  ok_actions          = var.alarm_actions
  tags                = local.tags
}
