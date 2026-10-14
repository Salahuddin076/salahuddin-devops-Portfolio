variable "primary_region" {
  description = "Region of the protected workloads and the primary vault."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.primary_region))
    error_message = "primary_region must be an AWS region name such as us-east-1."
  }
}

variable "dr_region" {
  description = "Recovery region: DR vault, restore testing, validator."
  type        = string
  default     = "us-west-2"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.dr_region))
    error_message = "dr_region must be an AWS region name such as us-west-2."
  }

  validation {
    condition     = var.dr_region != var.primary_region
    error_message = "dr_region must differ from primary_region: a same-region copy is not disaster recovery."
  }
}

variable "project" {
  description = "Value of the project default tag."
  type        = string
  default     = "aws-backup-cross-region-dr"
}

variable "owner" {
  description = "Value of the owner default tag."
  type        = string
  default     = "platform-team"
}

variable "break_glass_role_arn" {
  description = "Role allowed to delete recovery points. Account 123456789012 is a documentation placeholder."
  type        = string
  default     = "arn:aws:iam::123456789012:role/backup-break-glass"
}

variable "notification_emails" {
  description = "Subscribers for both regions' backup notification topics."
  type        = list(string)
  default     = []
}

variable "rds_test_subnet_group" {
  description = "DB subnet group in the DR region for restored test databases (isolated, no route to production)."
  type        = string
  default     = "restore-test-isolated"
}

variable "enable_audit_framework" {
  description = "Create the Backup Audit Manager framework (needs AWS Config recording)."
  type        = bool
  default     = false
}
