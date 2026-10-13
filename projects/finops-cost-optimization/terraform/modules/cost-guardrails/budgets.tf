resource "aws_budgets_budget" "monthly" {
  name         = "${var.name_prefix}-monthly-cost"
  budget_type  = "COST"
  limit_amount = format("%.2f", var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Credits and refunds would mask real consumption, so track gross spend.
  cost_types {
    include_credit = false
    include_refund = false
    include_tax    = true
  }

  dynamic "notification" {
    for_each = toset(var.actual_thresholds_pct)

    content {
      comparison_operator       = "GREATER_THAN"
      notification_type         = "ACTUAL"
      threshold                 = notification.value
      threshold_type            = "PERCENTAGE"
      subscriber_sns_topic_arns = [aws_sns_topic.alerts.arn]
    }
  }

  dynamic "notification" {
    for_each = toset(var.forecast_thresholds_pct)

    content {
      comparison_operator       = "GREATER_THAN"
      notification_type         = "FORECASTED"
      threshold                 = notification.value
      threshold_type            = "PERCENTAGE"
      subscriber_sns_topic_arns = [aws_sns_topic.alerts.arn]
    }
  }

  tags = var.tags

  depends_on = [aws_sns_topic_policy.alerts]
}
