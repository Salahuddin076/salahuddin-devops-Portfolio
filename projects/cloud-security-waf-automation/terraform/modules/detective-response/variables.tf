variable "name_prefix" {
  description = "Prefix for every resource name, e.g. secops-demo. Lowercase letters, digits and hyphens."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,31}$", var.name_prefix))
    error_message = "name_prefix must be 3-32 characters: a lowercase letter followed by lowercase letters, digits or hyphens."
  }
}

# ----------------------------------------------------------------------------- detectors

variable "enable_guardduty" {
  description = "Create the GuardDuty detector. Set false when the account already has one (one detector per account and region) or GuardDuty is managed by a delegated administrator."
  type        = bool
  default     = true
}

variable "guardduty_finding_publishing_frequency" {
  description = "How often updated findings are re-published to EventBridge. New findings are always published within about 5 minutes."
  type        = string
  default     = "FIFTEEN_MINUTES"

  validation {
    condition     = contains(["FIFTEEN_MINUTES", "ONE_HOUR", "SIX_HOURS"], var.guardduty_finding_publishing_frequency)
    error_message = "guardduty_finding_publishing_frequency must be FIFTEEN_MINUTES, ONE_HOUR or SIX_HOURS."
  }
}

variable "enable_security_hub" {
  description = "Enable Security Hub and subscribe to AWS Foundational Security Best Practices v1.0.0. Set false when it is managed centrally."
  type        = bool
  default     = true
}

# ----------------------------------------------------------------------------- routing

variable "guardduty_page_min_severity" {
  description = "GuardDuty findings at or above this severity go to the page topic. AWS labels 7.0-8.9 High and 9.0-10.0 Critical."
  type        = number
  default     = 7

  validation {
    condition     = var.guardduty_page_min_severity > 4 && var.guardduty_page_min_severity <= 10
    error_message = "guardduty_page_min_severity must be above 4 and at most 10."
  }
}

variable "guardduty_ticket_min_severity" {
  description = "GuardDuty findings from this severity up to (not including) the page threshold go to the ticket topic. Anything lower is not routed."
  type        = number
  default     = 4

  validation {
    condition     = var.guardduty_ticket_min_severity >= 1 && var.guardduty_ticket_min_severity < 10
    error_message = "guardduty_ticket_min_severity must be between 1 and 10."
  }
}

variable "page_subscriptions" {
  description = "Subscriptions on the page topic, e.g. an incident-management HTTPS endpoint. Email subscriptions must be confirmed by the recipient."
  type = list(object({
    protocol = string
    endpoint = string
  }))
  default = []

  validation {
    condition     = alltrue([for s in var.page_subscriptions : contains(["email", "https", "lambda", "sqs"], s.protocol)])
    error_message = "page_subscriptions protocol must be email, https, lambda or sqs."
  }
}

variable "ticket_subscriptions" {
  description = "Subscriptions on the ticket topic, e.g. an SQS queue drained into the ticketing system."
  type = list(object({
    protocol = string
    endpoint = string
  }))
  default = []

  validation {
    condition     = alltrue([for s in var.ticket_subscriptions : contains(["email", "https", "lambda", "sqs"], s.protocol)])
    error_message = "ticket_subscriptions protocol must be email, https, lambda or sqs."
  }
}

# ----------------------------------------------------------------------------- secrets rotation (optional)

variable "secret_rotation" {
  description = <<-EOT
    Optional rotation wiring for an existing secret. Takes an existing rotation
    Lambda (for example one deployed from the AWS Secrets Manager rotation
    templates); this module does not build one. The Lambda's resource policy
    must allow secretsmanager.amazonaws.com to invoke it.
  EOT
  type = object({
    secret_arn               = string
    rotation_lambda_arn      = string
    automatically_after_days = optional(number, 30)
  })
  default = null

  validation {
    condition = var.secret_rotation == null ? true : (
      can(regex("^arn:aws[a-z-]*:secretsmanager:", var.secret_rotation.secret_arn)) &&
      can(regex("^arn:aws[a-z-]*:lambda:", var.secret_rotation.rotation_lambda_arn)) &&
      var.secret_rotation.automatically_after_days >= 1 &&
      var.secret_rotation.automatically_after_days <= 1000
    )
    error_message = "secret_rotation needs a Secrets Manager secret ARN, a Lambda function ARN and automatically_after_days between 1 and 1000."
  }
}

variable "tags" {
  description = "Extra tags for every resource (the provider's default_tags still apply)."
  type        = map(string)
  default     = {}
}
