# Detective controls and the notification topics first: the WAF alarm
# publishes to the page topic.
module "detective" {
  source = "../../modules/detective-response"

  name_prefix         = "secops-demo"
  enable_guardduty    = var.enable_guardduty
  enable_security_hub = var.enable_security_hub

  page_subscriptions   = [for e in var.page_emails : { protocol = "email", endpoint = e }]
  ticket_subscriptions = [for e in var.ticket_emails : { protocol = "email", endpoint = e }]

  secret_rotation = var.secret_rotation

  tags = {
    cost-center = "security-engineering"
  }
}

module "waf" {
  source = "../../modules/waf"

  name_prefix = "edge-demo"
  scope       = "REGIONAL"

  # Count-then-block: established groups block, the SQLi group is new and
  # starts in count mode. One CommonRuleSet rule is excluded (counted) after
  # a confirmed false positive on file uploads (docs/operations.md).
  managed_rule_groups = {
    AWSManagedRulesAmazonIpReputationList = { priority = 10, mode = "block" }
    AWSManagedRulesCommonRuleSet          = { priority = 20, mode = "block", rules_to_count = ["SizeRestrictions_BODY"] }
    AWSManagedRulesKnownBadInputsRuleSet  = { priority = 30, mode = "block" }
    AWSManagedRulesSQLiRuleSet            = { priority = 40, mode = var.sqli_mode }
  }

  allow_ip_cidrs  = var.allow_ip_cidrs
  block_ip_cidrs  = var.block_ip_cidrs
  rate_limit      = 2000
  rate_limit_mode = var.rate_limit_mode

  associate_alb = var.alb_arn != null
  alb_arn       = var.alb_arn

  blocked_requests_alarm_threshold = 500
  alarm_actions                    = [module.detective.page_topic_arn]

  tags = {
    cost-center = "security-engineering"
  }
}
