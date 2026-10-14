variable "name_prefix" {
  description = "Prefix for every resource name, e.g. backup-dr-demo."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,29}$", var.name_prefix))
    error_message = "name_prefix must be 3-30 characters: lowercase letters, digits and hyphens, starting with a letter."
  }
}

# --------------------------------------------------------------------------
# Backup policy (normally jsondecode(file("policy/backup-policy.json")).plans)
# --------------------------------------------------------------------------

variable "backup_plans" {
  description = "One backup plan per tier (gold, silver). Each rule: schedule, lifecycle, optional continuous backup and optional copy to the DR vault with its own lifecycle."
  type = map(object({
    rules = list(object({
      name                       = string
      frequency                  = string
      schedule                   = string
      start_window_minutes       = optional(number, 60)
      completion_window_minutes  = optional(number, 480)
      delete_after_days          = number
      cold_storage_after_days    = optional(number)
      continuous                 = optional(bool, false)
      copy_to_dr                 = optional(bool, false)
      dr_delete_after_days       = optional(number)
      dr_cold_storage_after_days = optional(number)
    }))
  }))

  validation {
    condition     = length(var.backup_plans) > 0 && alltrue([for tier in keys(var.backup_plans) : contains(["gold", "silver"], tier)])
    error_message = "backup_plans keys must be gold and/or silver (the values of the backup-policy tag)."
  }

  validation {
    condition = alltrue(flatten([for p in values(var.backup_plans) : [
      for r in p.rules : r.cold_storage_after_days == null ? true : r.delete_after_days >= r.cold_storage_after_days + 90
    ]]))
    error_message = "Primary lifecycle: delete_after_days must be at least cold_storage_after_days + 90 (AWS Backup's minimum stay in cold storage)."
  }

  validation {
    condition = alltrue(flatten([for p in values(var.backup_plans) : [
      for r in p.rules : !r.copy_to_dr ? true : (
        r.dr_delete_after_days == null ? false : (
          r.dr_cold_storage_after_days == null ? true : r.dr_delete_after_days >= r.dr_cold_storage_after_days + 90
        )
      )
    ]]))
    error_message = "Copy lifecycle: copy_to_dr needs dr_delete_after_days, and dr_delete_after_days must be at least dr_cold_storage_after_days + 90."
  }

  validation {
    condition = alltrue(flatten([for p in values(var.backup_plans) : [
      for r in p.rules : !r.continuous ? true : (r.delete_after_days <= 35 && r.cold_storage_after_days == null)
    ]]))
    error_message = "Continuous backup (PITR) rules must keep at most 35 days and must not transition to cold storage."
  }

  validation {
    condition     = alltrue([for r in try(var.backup_plans["gold"].rules, []) : r.copy_to_dr])
    error_message = "Every gold rule must copy to the DR vault (copy_to_dr = true)."
  }

  validation {
    condition = alltrue(flatten([for p in values(var.backup_plans) : [
      for r in p.rules : can(regex("^cron\\(\\S+ \\S+ \\S+ \\S+ \\S+ \\S+\\)$", r.schedule))
    ]]))
    error_message = "Every schedule must be a six-field AWS cron expression: cron(min hour day-of-month month day-of-week year)."
  }

  validation {
    condition = !var.enable_vault_lock ? true : alltrue(flatten([for p in values(var.backup_plans) : [
      for r in p.rules : concat(
        [r.delete_after_days >= var.vault_lock_min_retention_days && r.delete_after_days <= var.vault_lock_max_retention_days],
        r.copy_to_dr && r.dr_delete_after_days != null ? [r.dr_delete_after_days >= var.vault_lock_min_retention_days && r.dr_delete_after_days <= var.vault_lock_max_retention_days] : []
      )
    ]]))
    error_message = "Every retention (primary and DR copy) must sit inside the vault lock range, or AWS Backup rejects the job."
  }
}

variable "selection_tag_key" {
  description = "Tag whose value (gold or silver) assigns a resource to a plan."
  type        = string
  default     = "backup-policy"
}

variable "exclude_tag_key" {
  description = "Resources tagged <key> = true are excluded even if they carry the tier tag."
  type        = string
  default     = "backup-exclude"
}

variable "schedule_timezone" {
  description = "Time zone for backup and restore-testing schedules."
  type        = string
  default     = "Etc/UTC"
}

variable "enable_continuous_backup" {
  description = "Turn on continuous backup (point-in-time recovery) for rules marked continuous. Applies to supported types (RDS, Aurora, S3, SAP HANA on EC2); others get snapshots."
  type        = bool
  default     = true
}

# --------------------------------------------------------------------------
# Vault Lock
# --------------------------------------------------------------------------

variable "enable_vault_lock" {
  description = "Apply Vault Lock to both vaults."
  type        = bool
  default     = true
}

variable "vault_lock_mode" {
  description = <<-EOT
    governance (default) or compliance.
    WARNING: compliance mode becomes IRREVERSIBLE once vault_lock_changeable_for_days
    has passed. After that nobody (not an administrator, not the root user, not
    AWS Support) can remove the lock, lower the minimum retention or delete the
    vault while it holds recovery points. Read docs/decisions/0002 first.
  EOT
  type        = string
  default     = "governance"

  validation {
    condition     = contains(["governance", "compliance"], var.vault_lock_mode)
    error_message = "vault_lock_mode must be governance or compliance."
  }
}

variable "vault_lock_min_retention_days" {
  description = "Shortest retention a recovery point in a locked vault may have."
  type        = number
  default     = 7

  validation {
    condition     = var.vault_lock_min_retention_days >= 1 && var.vault_lock_min_retention_days <= 36500 && floor(var.vault_lock_min_retention_days) == var.vault_lock_min_retention_days
    error_message = "vault_lock_min_retention_days must be a whole number of days between 1 and 36500."
  }
}

variable "vault_lock_max_retention_days" {
  description = "Longest retention a recovery point in a locked vault may have."
  type        = number
  default     = 400

  validation {
    condition     = var.vault_lock_max_retention_days >= 1 && var.vault_lock_max_retention_days <= 36500 && floor(var.vault_lock_max_retention_days) == var.vault_lock_max_retention_days
    error_message = "vault_lock_max_retention_days must be a whole number of days between 1 and 36500."
  }

  validation {
    condition     = var.vault_lock_max_retention_days >= var.vault_lock_min_retention_days
    error_message = "vault_lock_max_retention_days must be >= vault_lock_min_retention_days."
  }
}

variable "vault_lock_changeable_for_days" {
  description = "Compliance mode only: grace period (days) during which the lock can still be removed. Minimum 3. Ignored in governance mode."
  type        = number
  default     = 3

  validation {
    condition     = var.vault_lock_changeable_for_days >= 3
    error_message = "vault_lock_changeable_for_days must be at least 3 (the AWS minimum)."
  }
}

variable "break_glass_role_arn" {
  description = "The only role allowed to delete recovery points or shorten their lifecycle. Its use should page someone (see docs/operations.md)."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:role/.+$", var.break_glass_role_arn))
    error_message = "break_glass_role_arn must be an IAM role ARN."
  }
}

variable "kms_deletion_window_days" {
  description = "Waiting period for scheduled deletion of the four CMKs."
  type        = number
  default     = 30

  validation {
    condition     = var.kms_deletion_window_days >= 7 && var.kms_deletion_window_days <= 30
    error_message = "kms_deletion_window_days must be between 7 and 30."
  }
}

# --------------------------------------------------------------------------
# Alerting
# --------------------------------------------------------------------------

variable "vault_notification_events" {
  description = "Backup vault events sent to each region's SNS topic."
  type        = list(string)
  default = [
    "BACKUP_JOB_FAILED",
    "BACKUP_JOB_EXPIRED",
    "COPY_JOB_FAILED",
    "RESTORE_JOB_COMPLETED",
    "RESTORE_JOB_FAILED",
    "RECOVERY_POINT_MODIFIED",
  ]

  validation {
    condition = alltrue([for e in var.vault_notification_events : contains([
      "BACKUP_JOB_STARTED", "BACKUP_JOB_COMPLETED", "BACKUP_JOB_SUCCESSFUL", "BACKUP_JOB_FAILED", "BACKUP_JOB_EXPIRED",
      "COPY_JOB_STARTED", "COPY_JOB_SUCCESSFUL", "COPY_JOB_FAILED",
      "RESTORE_JOB_STARTED", "RESTORE_JOB_COMPLETED", "RESTORE_JOB_SUCCESSFUL", "RESTORE_JOB_FAILED",
      "RECOVERY_POINT_MODIFIED", "BACKUP_PLAN_CREATED", "BACKUP_PLAN_MODIFIED", "S3_BACKUP_OBJECT_FAILED", "S3_RESTORE_OBJECT_FAILED",
    ], e)])
    error_message = "vault_notification_events contains an unknown AWS Backup vault event."
  }
}

variable "notification_emails" {
  description = "Email subscribers for both regions' notification topics."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for e in var.notification_emails : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", e))])
    error_message = "notification_emails must be email addresses."
  }
}

variable "enable_job_alarms" {
  description = "CloudWatch alarms on NumberOfBackupJobsFailed and NumberOfCopyJobsFailed in both regions."
  type        = bool
  default     = true
}

# --------------------------------------------------------------------------
# Restore testing (DR region) and the validator Lambda
# --------------------------------------------------------------------------

variable "restore_testing" {
  description = "AWS Backup native restore testing against the DR vault: schedule and one selection per resource type."
  type = object({
    enabled               = optional(bool, true)
    schedule              = optional(string, "cron(0 6 ? * SUN *)")
    start_window_hours    = optional(number, 2)
    selection_window_days = optional(number, 7)
    selections = optional(map(object({
      resource_type              = string
      tier                       = optional(string, "gold")
      validation_window_hours    = optional(number, 4)
      restore_metadata_overrides = optional(map(string), {})
    })), {})
  })
  default = {}

  validation {
    condition = alltrue([for s in values(var.restore_testing.selections) : contains(
      ["RDS", "Aurora", "DynamoDB", "EBS", "EC2", "EFS", "FSx", "S3", "DocumentDB", "Neptune"], s.resource_type
    )])
    error_message = "restore_testing.selections[*].resource_type must be a type AWS Backup restore testing supports."
  }

  validation {
    condition     = alltrue([for s in values(var.restore_testing.selections) : s.validation_window_hours >= 1 && s.validation_window_hours <= 168])
    error_message = "validation_window_hours must be between 1 and 168."
  }

  validation {
    condition     = alltrue([for k in keys(var.restore_testing.selections) : can(regex("^[a-zA-Z0-9_]{1,50}$", k))])
    error_message = "restore_testing.selections keys become selection names: letters, digits and underscores only."
  }

  validation {
    condition     = var.restore_testing.selection_window_days >= 1 && var.restore_testing.selection_window_days <= 365
    error_message = "selection_window_days must be between 1 and 365."
  }
}

variable "restore_validator" {
  description = "The restore validator Lambda (src/restore_validator), triggered by completed restore-testing jobs in the DR region."
  type = object({
    enabled              = optional(bool, true)
    early_cleanup        = optional(bool, false)
    restore_test_tag_key = optional(string, "awsbackup-restore-test")
    dynamodb_min_items   = optional(number, 1)
    s3_min_objects       = optional(number, 1)
    s3_checksum_sample   = optional(number, 5)
    rds_row_count_query  = optional(string, "")
    log_retention_days   = optional(number, 30)
    subnet_ids           = optional(list(string), [])
    security_group_ids   = optional(list(string), [])
  })
  default = {}

  validation {
    condition     = (length(var.restore_validator.subnet_ids) == 0) == (length(var.restore_validator.security_group_ids) == 0)
    error_message = "Set both restore_validator.subnet_ids and security_group_ids (VPC access for the RDS reachability check) or neither."
  }

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.restore_validator.log_retention_days)
    error_message = "log_retention_days must be a CloudWatch Logs retention value."
  }
}

# --------------------------------------------------------------------------
# Audit Manager
# --------------------------------------------------------------------------

variable "audit_framework" {
  description = "AWS Backup Audit Manager framework (requires AWS Config recording in the primary region)."
  type = object({
    enabled                 = optional(bool, false)
    required_retention_days = optional(number, 35)
    required_frequency_days = optional(number, 1)
  })
  default = {}
}

variable "tags" {
  description = "Tags for every resource (on top of the provider default_tags)."
  type        = map(string)
  default     = {}
}
