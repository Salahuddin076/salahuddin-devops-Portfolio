variable "organization_id" {
  description = "Organization ID (o-...). Scopes the bucket and key policies with aws:SourceOrgID."
  type        = string

  validation {
    condition     = can(regex("^o-[a-z0-9]{10,32}$", var.organization_id))
    error_message = "organization_id must look like o-xxxxxxxxxx."
  }
}

variable "bucket_name" {
  description = "Name of the central log bucket in the log-archive account."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name must be a valid S3 bucket name (3-63 lower-case characters)."
  }
}

variable "trail_name" {
  description = "Name of the organization CloudTrail trail."
  type        = string
  default     = "lz-org-trail"
}

variable "object_lock_mode" {
  description = "Default Object Lock mode. GOVERNANCE lets a principal with s3:BypassGovernanceRetention (break-glass only, by bucket policy) remove a version; COMPLIANCE cannot be undone by anyone, including the root user, until retention ends."
  type        = string
  default     = "GOVERNANCE"

  validation {
    condition     = contains(["GOVERNANCE", "COMPLIANCE"], var.object_lock_mode)
    error_message = "object_lock_mode must be GOVERNANCE or COMPLIANCE."
  }
}

variable "object_lock_retention_days" {
  description = "Default Object Lock retention for new log objects, in days."
  type        = number
  default     = 365

  validation {
    condition     = var.object_lock_retention_days >= 1 && var.object_lock_retention_days <= 3650
    error_message = "object_lock_retention_days must be between 1 and 3650."
  }
}

variable "glacier_transition_days" {
  description = "Days after which log objects move to S3 Glacier Flexible Retrieval."
  type        = number
  default     = 90
}

variable "log_expiration_days" {
  description = "Days after which log objects expire. Must exceed the Object Lock retention and the Glacier transition."
  type        = number
  default     = 2555
}

variable "config_aggregator_name" {
  description = "Name of the organization-wide AWS Config aggregator."
  type        = string
  default     = "lz-org-aggregator"
}

variable "break_glass_role_name" {
  description = "Role in the log-archive account that may bypass governance retention."
  type        = string
  default     = "LandingZoneBreakGlass"
}

variable "kms_deletion_window_days" {
  description = "Waiting period before the log key is deleted after scheduling."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags for log-archive resources."
  type        = map(string)
  default     = {}
}
