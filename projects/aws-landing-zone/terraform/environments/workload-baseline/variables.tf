variable "region" {
  description = "Region for regional baseline resources (must be in the SCP region allow-list)."
  type        = string
  default     = "us-east-1"
}

variable "workload_role_arn" {
  description = "Role assumed in the workload account."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:role/.+$", var.workload_role_arn))
    error_message = "workload_role_arn must be an IAM role ARN."
  }
}

variable "environment" {
  description = "Environment tag value: prod, nonprod, shared or sandbox (tag policy values)."
  type        = string

  validation {
    condition     = contains(["prod", "nonprod", "shared", "sandbox"], var.environment)
    error_message = "environment must be prod, nonprod, shared or sandbox."
  }
}

variable "owner" {
  description = "Owner tag value (one of the tag policy values)."
  type        = string
  default     = "platform-team"
}

variable "cost_center" {
  description = "CostCenter tag value (one of the tag policy values)."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly budget for the account."
  type        = number
}

variable "budget_alert_emails" {
  description = "Budget alert recipients."
  type        = list(string)
  default     = []
}

variable "spoke_name" {
  description = "Key in policy/cidr-plan.json for this account's spoke VPC; null for no spoke (sandbox accounts)."
  type        = string
  default     = null
}

variable "transit_gateway_id" {
  description = "Shared Transit Gateway ID (shared-services output); required when spoke_name is set."
  type        = string
  default     = null
}

variable "azs" {
  description = "Availability zones for the spoke VPC."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}
