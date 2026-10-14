variable "vault_name" {
  description = "Backup vault name."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9-_]{2,50}$", var.vault_name))
    error_message = "vault_name must be 2-50 characters: letters, digits, hyphens, underscores."
  }
}

variable "vault_role" {
  description = "primary or dr. Used in names, descriptions and tags only."
  type        = string

  validation {
    condition     = contains(["primary", "dr"], var.vault_role)
    error_message = "vault_role must be primary or dr."
  }
}

variable "backup_role_arns" {
  description = "IAM roles that back up into, copy into or restore from this vault. They get use of the vault key."
  type        = list(string)
}

variable "break_glass_role_arn" {
  description = "The only principal the vault access policy lets delete recovery points or shorten their lifecycle."
  type        = string
}

variable "copy_source_account_ids" {
  description = "Other AWS accounts allowed to copy into this vault (cross-account DR). Empty for single-account."
  type        = list(string)
  default     = []
}

variable "kms_deletion_window_days" {
  description = "Waiting period before a scheduled key deletion completes."
  type        = number
  default     = 30
}

variable "vault_lock" {
  description = "Vault Lock settings. changeable_for_days = null is governance mode; a number is compliance mode with that grace period."
  type = object({
    enabled             = bool
    min_retention_days  = number
    max_retention_days  = number
    changeable_for_days = optional(number)
  })
}

variable "notification_events" {
  description = "Backup vault events published to this region's notification topic."
  type        = list(string)
}

variable "notification_emails" {
  description = "Email subscribers for this region's notification topic (each must confirm)."
  type        = list(string)
  default     = []
}

variable "enable_job_alarms" {
  description = "Create CloudWatch alarms on failed backup and copy jobs in this region."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
  default     = {}
}
