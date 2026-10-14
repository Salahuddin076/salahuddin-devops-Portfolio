output "budget_topic_arn" {
  description = "Budget alert topic."
  value       = module.baseline.budget_topic_arn
}

output "access_analyzer_arn" {
  description = "IAM Access Analyzer."
  value       = module.baseline.access_analyzer_arn
}

output "transit_gateway_attachment_id" {
  description = "Record in the shared-services spoke_attachment_ids (null without a spoke)."
  value       = one(module.spoke_vpc[*].transit_gateway_attachment_id)
}
