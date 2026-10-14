output "orders_endpoint" {
  description = "POST orders here."
  value       = module.order_pipeline.orders_endpoint
}

output "queue_arn" {
  description = "Main queue ARN (redrive destination)."
  value       = module.order_pipeline.queue_arn
}

output "dlq_arn" {
  description = "Dead-letter queue ARN (redrive source)."
  value       = module.order_pipeline.dlq_arn
}

output "table_name" {
  description = "Orders and idempotency table."
  value       = module.order_pipeline.table_name
}

output "event_bus_name" {
  description = "Custom EventBridge bus."
  value       = module.order_pipeline.event_bus_name
}

output "alarms_topic_arn" {
  description = "Alarm notifications topic."
  value       = module.order_pipeline.alarms_topic_arn
}

output "function_names" {
  description = "Lambda function names."
  value       = module.order_pipeline.function_names
}

output "dlq_url" {
  description = "Dead-letter queue URL (for inspecting messages)."
  value       = module.order_pipeline.dlq_url
}
