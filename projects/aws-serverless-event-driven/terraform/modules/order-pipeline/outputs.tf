output "orders_endpoint" {
  description = "POST orders here (needs an Idempotency-Key header)."
  value       = "${aws_apigatewayv2_stage.default.invoke_url}orders"
}

output "api_id" {
  description = "HTTP API ID."
  value       = aws_apigatewayv2_api.orders.id
}

output "queue_url" {
  description = "Main orders queue URL."
  value       = aws_sqs_queue.orders.url
}

output "queue_arn" {
  description = "Main orders queue ARN (the redrive destination)."
  value       = aws_sqs_queue.orders.arn
}

output "dlq_url" {
  description = "Dead-letter queue URL."
  value       = aws_sqs_queue.dlq.url
}

output "dlq_arn" {
  description = "Dead-letter queue ARN (the redrive source for start-message-move-task)."
  value       = aws_sqs_queue.dlq.arn
}

output "table_name" {
  description = "DynamoDB table holding idempotency records and order state."
  value       = aws_dynamodb_table.orders.name
}

output "event_bus_name" {
  description = "Custom EventBridge bus for order domain events."
  value       = aws_cloudwatch_event_bus.orders.name
}

output "notifications_topic_arn" {
  description = "SNS topic receiving OrderAccepted notifications."
  value       = aws_sns_topic.notifications.arn
}

output "alarms_topic_arn" {
  description = "SNS topic receiving CloudWatch alarm notifications."
  value       = aws_sns_topic.alarms.arn
}

output "function_names" {
  description = "Lambda function names."
  value       = local.functions
}

output "log_group_names" {
  description = "CloudWatch log groups for the functions and API access logs."
  value = {
    ingest     = aws_cloudwatch_log_group.ingest.name
    process    = aws_cloudwatch_log_group.process.name
    api_access = aws_cloudwatch_log_group.api_access.name
  }
}
