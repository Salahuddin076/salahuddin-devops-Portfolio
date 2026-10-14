variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.region))
    error_message = "region must look like an AWS region code, e.g. us-east-1."
  }
}

variable "project" {
  description = "Value for the project default tag."
  type        = string
  default     = "cloud-security-waf-automation"
}

variable "owner" {
  description = "Value for the owner default tag (team accountable for the stack)."
  type        = string
  default     = "security-engineering"
}

variable "alb_arn" {
  description = "Existing internet-facing ALB to protect. Leave null to create the web ACL without an association. Must be a literal here (the module's association count depends on it); pass associate_alb directly when the ARN comes from another resource."
  type        = string
  default     = null
}

variable "allow_ip_cidrs" {
  description = "Always-allowed IPv4 ranges, e.g. a synthetic monitoring range."
  type        = list(string)
  default     = ["192.0.2.0/28"]

  validation {
    condition     = alltrue([for c in var.allow_ip_cidrs : can(cidrnetmask(c))])
    error_message = "allow_ip_cidrs must be IPv4 CIDRs."
  }
}

variable "block_ip_cidrs" {
  description = "Blocked IPv4 ranges."
  type        = list(string)
  default     = ["198.51.100.0/24"]

  validation {
    condition     = alltrue([for c in var.block_ip_cidrs : can(cidrnetmask(c))])
    error_message = "block_ip_cidrs must be IPv4 CIDRs."
  }
}

variable "sqli_mode" {
  description = "Mode of the SQLi managed rule group: count until the log summary shows no false positives, then block."
  type        = string
  default     = "count"

  validation {
    condition     = contains(["count", "block"], var.sqli_mode)
    error_message = "sqli_mode must be \"count\" or \"block\"."
  }
}

variable "rate_limit_mode" {
  description = "Mode of the per-IP rate rule."
  type        = string
  default     = "count"

  validation {
    condition     = contains(["count", "block"], var.rate_limit_mode)
    error_message = "rate_limit_mode must be \"count\" or \"block\"."
  }
}

variable "enable_guardduty" {
  description = "Create a GuardDuty detector (false if the account already has one)."
  type        = bool
  default     = true
}

variable "enable_security_hub" {
  description = "Enable Security Hub with FSBP (false if managed centrally)."
  type        = bool
  default     = true
}

variable "page_emails" {
  description = "Who gets paged (email subscriptions need confirming)."
  type        = list(string)
  default     = ["secops-oncall@example.com"]

  validation {
    condition     = alltrue([for e in var.page_emails : can(regex("^[^@\\s]+@[^@\\s]+\\.[a-z]{2,}$", e))])
    error_message = "page_emails must be email addresses."
  }
}

variable "ticket_emails" {
  description = "Where ticket-level findings go."
  type        = list(string)
  default     = ["secops-queue@example.com"]

  validation {
    condition     = alltrue([for e in var.ticket_emails : can(regex("^[^@\\s]+@[^@\\s]+\\.[a-z]{2,}$", e))])
    error_message = "ticket_emails must be email addresses."
  }
}

variable "secret_rotation" {
  description = "Optional: rotate an existing secret with an existing rotation Lambda (see the module variable)."
  type = object({
    secret_arn               = string
    rotation_lambda_arn      = string
    automatically_after_days = optional(number, 30)
  })
  default = null
}
