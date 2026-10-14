output "page_topic_arn" {
  description = "SNS topic for page-worthy findings (also a good target for the WAF blocked-requests alarm)."
  value       = aws_sns_topic.page.arn
}

output "ticket_topic_arn" {
  description = "SNS topic for ticket-worthy findings."
  value       = aws_sns_topic.ticket.arn
}

output "kms_key_arn" {
  description = "CMK encrypting both topics."
  value       = aws_kms_key.sns.arn
}

output "guardduty_detector_id" {
  description = "GuardDuty detector ID, or null when enable_guardduty is false."
  value       = one(aws_guardduty_detector.this[*].id)
}

output "event_rule_names" {
  description = "EventBridge routing rules by route key."
  value       = { for k, r in aws_cloudwatch_event_rule.route : k => r.name }
}

output "secret_rotation_enabled" {
  description = "Whether rotation wiring was created."
  value       = length(aws_secretsmanager_secret_rotation.this) > 0
}
