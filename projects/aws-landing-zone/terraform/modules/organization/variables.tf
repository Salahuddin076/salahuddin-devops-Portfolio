variable "aws_service_access_principals" {
  description = "Services with trusted access to the organization. CloudTrail, Config, GuardDuty, Security Hub and IAM Identity Center are required by the rest of the landing zone."
  type        = list(string)
  default = [
    "access-analyzer.amazonaws.com",
    "cloudtrail.amazonaws.com",
    "config.amazonaws.com",
    "config-multiaccountsetup.amazonaws.com",
    "guardduty.amazonaws.com",
    "malware-protection.guardduty.amazonaws.com",
    "ram.amazonaws.com",
    "securityhub.amazonaws.com",
    "sso.amazonaws.com",
  ]

  validation {
    condition = alltrue([
      for p in ["cloudtrail.amazonaws.com", "config.amazonaws.com", "guardduty.amazonaws.com", "securityhub.amazonaws.com", "sso.amazonaws.com"] :
      contains(var.aws_service_access_principals, p)
    ])
    error_message = "aws_service_access_principals must include cloudtrail, config, guardduty, securityhub and sso (*.amazonaws.com)."
  }
}

variable "accounts" {
  description = "Member accounts to create, keyed by a short stable key (used in outputs and by other modules). ou must be one of: security, infrastructure, workloads, prod, nonprod, sandbox, suspended."
  type = map(object({
    name  = string
    email = string
    ou    = string
  }))
  default = {}

  validation {
    # This repository only uses the documentation domain. A real deployment
    # replaces example.com with the company domain (plus-addressing works).
    condition     = alltrue([for a in values(var.accounts) : can(regex("^[a-z0-9][a-z0-9.+_-]*@example\\.com$", a.email))])
    error_message = "Every account email must be a lower-case address at example.com (synthetic values only in this repository)."
  }

  validation {
    condition     = length(distinct([for a in values(var.accounts) : a.email])) == length(var.accounts)
    error_message = "Account emails must be unique: AWS uses the email as the root user identity."
  }

  validation {
    condition     = alltrue([for a in values(var.accounts) : can(regex("^[a-z][a-z0-9-]{1,48}[a-z0-9]$", a.name))])
    error_message = "Account names must be 3-50 characters of lower-case letters, digits and hyphens, starting with a letter."
  }

  validation {
    condition     = alltrue([for a in values(var.accounts) : contains(["security", "infrastructure", "workloads", "prod", "nonprod", "sandbox", "suspended"], a.ou)])
    error_message = "Account ou must be one of: security, infrastructure, workloads, prod, nonprod, sandbox, suspended."
  }
}

variable "delegated_administrators" {
  description = "Service principal -> account key to register as delegated administrator through the Organizations API (for example config.amazonaws.com, access-analyzer.amazonaws.com). GuardDuty and Security Hub use their own admin-account resources instead: see security_tooling_account_key."
  type        = map(string)
  default     = {}

  validation {
    condition     = !anytrue([for p in keys(var.delegated_administrators) : contains(["guardduty.amazonaws.com", "securityhub.amazonaws.com"], p)])
    error_message = "Register GuardDuty and Security Hub administrators with security_tooling_account_key, not the generic Organizations API."
  }
}

variable "security_tooling_account_key" {
  description = "Account key that becomes the GuardDuty and Security Hub delegated administrator. null skips both registrations."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags for the OUs and accounts."
  type        = map(string)
  default     = {}
}
