output "web_acl_arn" {
  description = "Web ACL ARN (attach it to a CloudFront distribution's web_acl_id for CLOUDFRONT scope)."
  value       = aws_wafv2_web_acl.this.arn
}

output "web_acl_name" {
  description = "Web ACL name (the WebACL dimension of the AWS/WAFV2 metrics)."
  value       = aws_wafv2_web_acl.this.name
}

output "web_acl_capacity" {
  description = "WCUs used by the web ACL. Above 1,500 AWS charges extra per request."
  value       = aws_wafv2_web_acl.this.capacity
}

output "log_group_name" {
  description = "CloudWatch log group receiving WAF logs (export as JSON lines for scripts/waf_log_summary.py)."
  value       = aws_cloudwatch_log_group.waf.name
}

output "rule_modes" {
  description = "Effective count/block mode of every rule, for the rollout tracker."
  value = merge(
    { for name, g in local.enabled_managed_groups : "AWS-${name}" => g.mode },
    length(var.block_ip_cidrs) > 0 ? { "ip-block-list" = var.block_list_mode } : {},
    var.rate_limit == null ? {} : { "rate-limit-per-ip" = var.rate_limit_mode },
  )
}

output "blocked_requests_alarm_arn" {
  description = "Blocked-requests spike alarm."
  value       = aws_cloudwatch_metric_alarm.blocked_spike.arn
}
