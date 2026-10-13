output "alerts_topic_arn" {
  description = "SNS topic receiving budget and anomaly notifications."
  value       = module.cost_guardrails.alerts_topic_arn
}

output "budget_name" {
  description = "Monthly cost budget name."
  value       = module.cost_guardrails.budget_name
}

output "export_s3_uri" {
  description = "Where the FOCUS export lands."
  value       = module.cost_guardrails.export_s3_uri
}
