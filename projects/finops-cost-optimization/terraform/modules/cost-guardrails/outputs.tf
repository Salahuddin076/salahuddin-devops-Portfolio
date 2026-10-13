output "alerts_topic_arn" {
  description = "SNS topic receiving budget and anomaly notifications."
  value       = aws_sns_topic.alerts.arn
}

output "alerts_kms_key_arn" {
  description = "KMS key encrypting the alerts topic."
  value       = aws_kms_key.alerts.arn
}

output "budget_name" {
  description = "Name of the monthly cost budget."
  value       = aws_budgets_budget.monthly.name
}

output "anomaly_monitor_arn" {
  description = "Cost Anomaly Detection monitor the subscription is attached to."
  value       = local.anomaly_monitor_arn
}

output "anomaly_subscription_arn" {
  description = "Cost Anomaly Detection subscription ARN."
  value       = aws_ce_anomaly_subscription.alerts.arn
}

output "export_bucket_name" {
  description = "S3 bucket receiving the FOCUS export (null when create_data_export = false)."
  value       = try(aws_s3_bucket.exports[0].bucket, null)
}

output "export_arn" {
  description = "ARN of the BCM Data Exports FOCUS export (null when create_data_export = false)."
  value       = try(aws_bcmdataexports_export.focus[0].export[0].export_arn, null)
}

output "export_s3_uri" {
  description = "Where export files land; point the toolkit's ingestion at this prefix."
  value       = var.create_data_export ? "s3://${aws_s3_bucket.exports[0].bucket}/${var.export_s3_prefix}/" : null
}
