resource "aws_ce_anomaly_monitor" "services" {
  count = var.existing_anomaly_monitor_arn == null ? 1 : 0

  name              = "${var.name_prefix}-aws-services"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
  tags              = var.tags
}

locals {
  anomaly_monitor_arn = coalesce(var.existing_anomaly_monitor_arn, try(aws_ce_anomaly_monitor.services[0].arn, null))
}

resource "aws_ce_anomaly_subscription" "alerts" {
  name             = "${var.name_prefix}-anomaly-alerts"
  frequency        = "IMMEDIATE" # SNS subscribers require IMMEDIATE
  monitor_arn_list = [local.anomaly_monitor_arn]

  subscriber {
    type    = "SNS"
    address = aws_sns_topic.alerts.arn
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = [tostring(var.anomaly_impact_threshold_usd)]
    }
  }

  tags = var.tags

  depends_on = [aws_sns_topic_policy.alerts]
}
