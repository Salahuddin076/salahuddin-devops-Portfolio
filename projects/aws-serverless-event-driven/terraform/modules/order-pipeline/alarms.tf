locals {
  alarm_actions = [aws_sns_topic.alarms.arn]

  functions = {
    ingest  = aws_lambda_function.ingest.function_name
    process = aws_lambda_function.process.function_name
  }
}

# Anything in the DLQ is an order that was not accepted. Zero tolerance.
resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "${var.name_prefix}-dlq-not-empty"
  alarm_description   = "Messages in ${aws_sqs_queue.dlq.name}. Runbook: docs/operations.md#dlq-not-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
  tags                = var.tags
}

# The processor is falling behind (or stuck on an in-progress lock).
resource "aws_cloudwatch_metric_alarm" "queue_oldest_message_age" {
  alarm_name          = "${var.name_prefix}-queue-oldest-message-age"
  alarm_description   = "Oldest message in ${aws_sqs_queue.orders.name} older than ${var.oldest_message_age_alarm_seconds}s. Runbook: docs/operations.md#queue-oldest-message-age"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = aws_sqs_queue.orders.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = var.oldest_message_age_alarm_seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
  tags                = var.tags
}

# Whole-invocation failures. For the processor, per-record failures are
# returned as batchItemFailures and do NOT count here; they surface as
# retries, queue age and, eventually, DLQ depth.
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = local.functions

  alarm_name          = "${var.name_prefix}-${each.key}-errors"
  alarm_description   = "${each.value} invocation errors. Runbook: docs/operations.md#lambda-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = each.value }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
  tags                = var.tags
}

resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  for_each = local.functions

  alarm_name          = "${var.name_prefix}-${each.key}-throttles"
  alarm_description   = "${each.value} throttled. Runbook: docs/operations.md#lambda-throttles"
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = each.value }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
  tags                = var.tags
}

# EventBridge could not deliver to SNS after its retry policy.
resource "aws_cloudwatch_metric_alarm" "rule_failed_invocations" {
  alarm_name          = "${var.name_prefix}-order-accepted-failed-invocations"
  alarm_description   = "EventBridge rule ${aws_cloudwatch_event_rule.order_accepted.name} failed to deliver. Runbook: docs/operations.md#eventbridge-failed-invocations"
  namespace           = "AWS/Events"
  metric_name         = "FailedInvocations"
  dimensions          = { EventBusName = aws_cloudwatch_event_bus.orders.name, RuleName = aws_cloudwatch_event_rule.order_accepted.name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
  tags                = var.tags
}

# Server-side errors at the API edge (ingest crashes or SQS unavailable).
resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${var.name_prefix}-api-5xx"
  alarm_description   = "HTTP API 5xx responses. Runbook: docs/operations.md#api-5xx"
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  dimensions          = { ApiId = aws_apigatewayv2_api.orders.id, Stage = aws_apigatewayv2_stage.default.name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
  tags                = var.tags
}
