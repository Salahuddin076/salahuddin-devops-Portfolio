variable "name_prefix" {
  description = "Prefix for every resource name, e.g. edge-demo. Lowercase letters, digits and hyphens."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,31}$", var.name_prefix))
    error_message = "name_prefix must be 3-32 characters: a lowercase letter followed by lowercase letters, digits or hyphens."
  }
}

variable "scope" {
  description = "REGIONAL (ALB, API Gateway, AppSync, Cognito) or CLOUDFRONT. A CLOUDFRONT web ACL must be created through a provider in us-east-1."
  type        = string
  default     = "REGIONAL"

  validation {
    condition     = contains(["REGIONAL", "CLOUDFRONT"], var.scope)
    error_message = "scope must be REGIONAL or CLOUDFRONT."
  }
}

# ----------------------------------------------------------------------------- managed rule groups

variable "managed_rule_groups" {
  description = <<-EOT
    AWS managed rule groups, keyed by rule group name (vendor AWS). Each entry:
    enabled, priority (unique across the web ACL), mode ("count" or "block"),
    and rules_to_count: rules inside the group overridden to COUNT (the
    exclusion used for a confirmed false positive). New groups start in count
    mode; see docs/decisions/0001-count-before-block.md.
  EOT
  type = map(object({
    enabled        = optional(bool, true)
    priority       = number
    mode           = optional(string, "count")
    rules_to_count = optional(list(string), [])
  }))
  default = {
    AWSManagedRulesAmazonIpReputationList = { priority = 10, mode = "block" }
    AWSManagedRulesCommonRuleSet          = { priority = 20, mode = "block" }
    AWSManagedRulesKnownBadInputsRuleSet  = { priority = 30, mode = "block" }
    AWSManagedRulesSQLiRuleSet            = { priority = 40, mode = "count", enabled = false }
  }

  validation {
    condition = alltrue([
      for name, g in var.managed_rule_groups : contains([
        "AWSManagedRulesAmazonIpReputationList",
        "AWSManagedRulesCommonRuleSet",
        "AWSManagedRulesKnownBadInputsRuleSet",
        "AWSManagedRulesSQLiRuleSet",
      ], name)
    ])
    error_message = "managed_rule_groups keys must be one of AWSManagedRulesAmazonIpReputationList, AWSManagedRulesCommonRuleSet, AWSManagedRulesKnownBadInputsRuleSet, AWSManagedRulesSQLiRuleSet."
  }

  validation {
    condition     = alltrue([for g in var.managed_rule_groups : contains(["count", "block"], g.mode)])
    error_message = "Each managed rule group mode must be \"count\" or \"block\"."
  }

  validation {
    condition     = alltrue([for g in var.managed_rule_groups : g.priority >= 10 && g.priority < 1000])
    error_message = "Managed rule group priorities must be between 10 and 999 (0-9 are reserved for the IP lists and the rate rule)."
  }
}

# ----------------------------------------------------------------------------- IP lists

variable "allow_ip_cidrs" {
  description = "IPv4 CIDRs that are always allowed (evaluated first, priority 0). Keep this short: an allowed request skips every later rule."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for c in var.allow_ip_cidrs : can(cidrnetmask(c))])
    error_message = "allow_ip_cidrs must be IPv4 CIDRs, e.g. 192.0.2.0/24."
  }
}

variable "block_ip_cidrs" {
  description = "IPv4 CIDRs to block (priority 1)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for c in var.block_ip_cidrs : can(cidrnetmask(c))])
    error_message = "block_ip_cidrs must be IPv4 CIDRs, e.g. 198.51.100.0/24."
  }
}

variable "block_list_mode" {
  description = "Action of the IP block-list rule: count or block."
  type        = string
  default     = "block"

  validation {
    condition     = contains(["count", "block"], var.block_list_mode)
    error_message = "block_list_mode must be \"count\" or \"block\"."
  }
}

# ----------------------------------------------------------------------------- rate limit

variable "rate_limit" {
  description = "Requests per client IP per evaluation window before the rate rule matches. Set null to omit the rule."
  type        = number
  default     = 2000

  validation {
    condition     = var.rate_limit == null ? true : (var.rate_limit >= 10 && var.rate_limit <= 2000000000)
    error_message = "rate_limit must be between 10 and 2000000000, or null."
  }
}

variable "rate_limit_window_seconds" {
  description = "Rate rule evaluation window in seconds."
  type        = number
  default     = 300

  validation {
    condition     = contains([60, 120, 300, 600], var.rate_limit_window_seconds)
    error_message = "rate_limit_window_seconds must be 60, 120, 300 or 600."
  }
}

variable "rate_limit_mode" {
  description = "Action of the rate-based rule: count or block."
  type        = string
  default     = "count"

  validation {
    condition     = contains(["count", "block"], var.rate_limit_mode)
    error_message = "rate_limit_mode must be \"count\" or \"block\"."
  }
}

# ----------------------------------------------------------------------------- logging

variable "log_retention_days" {
  description = "Retention of the aws-waf-logs-* log group."
  type        = number
  default     = 30

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be a value CloudWatch Logs accepts (1, 3, 5, 7, 14, 30, 60, 90, ...)."
  }
}

variable "log_kms_key_arn" {
  description = "Optional KMS key ARN for the log group. The key policy must allow logs.<region>.amazonaws.com to use it."
  type        = string
  default     = null

  validation {
    condition     = var.log_kms_key_arn == null || can(regex("^arn:aws[a-z-]*:kms:", var.log_kms_key_arn))
    error_message = "log_kms_key_arn must be a KMS key ARN."
  }
}

variable "create_log_resource_policy" {
  description = "Create the CloudWatch Logs resource policy that lets delivery.logs.amazonaws.com write to aws-waf-logs-* groups. Set false if the account already has one (the limit is 10 per region)."
  type        = bool
  default     = true
}

variable "redacted_headers" {
  description = "Request headers replaced with REDACTED in WAF logs."
  type        = list(string)
  default     = ["authorization", "cookie"]

  validation {
    condition     = alltrue([for h in var.redacted_headers : can(regex("^[a-z0-9-]+$", h))])
    error_message = "redacted_headers must be lowercase header names."
  }
}

# ----------------------------------------------------------------------------- association

variable "associate_alb" {
  description = "Associate the web ACL with alb_arn. A separate flag so the count is known at plan time even when the ARN is not. REGIONAL scope only."
  type        = bool
  default     = false
}

variable "alb_arn" {
  description = "Application Load Balancer ARN to protect when associate_alb is true."
  type        = string
  default     = null

  validation {
    condition     = var.alb_arn == null || can(regex("^arn:aws[a-z-]*:elasticloadbalancing:[a-z0-9-]+:[0-9]{12}:loadbalancer/app/", var.alb_arn))
    error_message = "alb_arn must be an Application Load Balancer ARN (loadbalancer/app/...)."
  }
}

# ----------------------------------------------------------------------------- alarm

variable "blocked_requests_alarm_threshold" {
  description = "Alarm when the web ACL blocks more than this many requests in one alarm period."
  type        = number
  default     = 500

  validation {
    condition     = var.blocked_requests_alarm_threshold > 0
    error_message = "blocked_requests_alarm_threshold must be positive."
  }
}

variable "alarm_period_seconds" {
  description = "Alarm period in seconds."
  type        = number
  default     = 300

  validation {
    condition     = contains([60, 300, 900, 3600], var.alarm_period_seconds)
    error_message = "alarm_period_seconds must be 60, 300, 900 or 3600."
  }
}

variable "alarm_actions" {
  description = "SNS topic ARNs notified when the blocked-requests alarm fires."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Extra tags for every resource (the provider's default_tags still apply)."
  type        = map(string)
  default     = {}
}
