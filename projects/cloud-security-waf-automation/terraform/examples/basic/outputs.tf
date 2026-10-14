output "web_acl_arn" {
  description = "Web ACL ARN."
  value       = module.waf.web_acl_arn
}

output "waf_log_group" {
  description = "WAF log group (aws-waf-logs-*)."
  value       = module.waf.log_group_name
}

output "rule_modes" {
  description = "Count/block mode per rule: the rollout state at a glance."
  value       = module.waf.rule_modes
}

output "page_topic_arn" {
  description = "Page topic."
  value       = module.detective.page_topic_arn
}

output "ticket_topic_arn" {
  description = "Ticket topic."
  value       = module.detective.ticket_topic_arn
}

output "event_rule_names" {
  description = "EventBridge finding-routing rules."
  value       = module.detective.event_rule_names
}
