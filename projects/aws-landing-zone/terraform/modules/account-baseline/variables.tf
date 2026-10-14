variable "name_prefix" {
  description = "Prefix for baseline resource names."
  type        = string
  default     = "lz"
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget for the account, in USD."
  type        = number

  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be positive."
  }
}

variable "budget_thresholds" {
  description = "Alert thresholds as percentages of the budget. Actual spend alerts at each; a forecast alert fires at 100."
  type        = list(number)
  default     = [50, 80, 100]

  validation {
    condition     = length(var.budget_thresholds) > 0 && alltrue([for t in var.budget_thresholds : t > 0 && t <= 1000])
    error_message = "budget_thresholds must be percentages between 1 and 1000."
  }
}

variable "budget_alert_emails" {
  description = "Email addresses subscribed to the budget topic (each must confirm the subscription)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for e in var.budget_alert_emails : can(regex("^[^@\\s]+@example\\.com$", e))])
    error_message = "Use example.com addresses in this repository."
  }
}

variable "password_min_length" {
  description = "Minimum IAM user password length. IAM users should be rare (break-glass only); people use Identity Center."
  type        = number
  default     = 16

  validation {
    condition     = var.password_min_length >= 14 && var.password_min_length <= 128
    error_message = "password_min_length must be between 14 and 128."
  }
}

variable "access_analyzer_type" {
  description = "ACCOUNT for a per-account analyzer, ORGANIZATION only in the Access Analyzer delegated administrator."
  type        = string
  default     = "ACCOUNT"

  validation {
    condition     = contains(["ACCOUNT", "ORGANIZATION"], var.access_analyzer_type)
    error_message = "access_analyzer_type must be ACCOUNT or ORGANIZATION."
  }
}

variable "tags" {
  description = "Tags for baseline resources."
  type        = map(string)
  default     = {}
}
