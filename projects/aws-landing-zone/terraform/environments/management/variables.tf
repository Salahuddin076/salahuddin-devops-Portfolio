variable "region" {
  description = "Home region of the landing zone (Identity Center, org trail home region). Must be in the region allow-list."
  type        = string
  default     = "us-east-1"
}

variable "management_role_arn" {
  description = "Deployer role in the management account."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:role/.+$", var.management_role_arn))
    error_message = "management_role_arn must be an IAM role ARN."
  }
}

variable "log_archive_role_arn" {
  description = "Role assumed in the log-archive account (OrganizationAccountAccessRole after vending)."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:role/.+$", var.log_archive_role_arn))
    error_message = "log_archive_role_arn must be an IAM role ARN."
  }
}

variable "accounts" {
  description = "Member accounts: key -> { name, email, ou }. See the organization module."
  type = map(object({
    name  = string
    email = string
    ou    = string
  }))
}

variable "delegated_administrators" {
  description = "Service principal -> account key, registered through the Organizations API."
  type        = map(string)
  default     = {}
}

variable "security_tooling_account_key" {
  description = "Account key for the GuardDuty and Security Hub delegated administrator."
  type        = string
  default     = null
}

variable "identity_center_group_ids" {
  description = "Identity store group name -> group ID (groups are synced from the IdP, not created here)."
  type        = map(string)
}

variable "identity_center_assignments" {
  description = "Group name -> account key -> permission set names."
  type        = map(map(list(string)))
}

variable "log_bucket_name" {
  description = "Central log bucket name in the log-archive account."
  type        = string
}

variable "object_lock_retention_days" {
  description = "Default Object Lock (governance) retention for log objects."
  type        = number
  default     = 365
}

variable "cost_center" {
  description = "CostCenter tag for landing zone resources (one of the tag policy values)."
  type        = string
  default     = "CC-9000"
}
