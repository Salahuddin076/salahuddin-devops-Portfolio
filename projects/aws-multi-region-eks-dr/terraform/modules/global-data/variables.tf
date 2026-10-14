variable "name" {
  description = "Name prefix (for example dr-app). Region-specific resources append the region, never a role, because roles swap on failover."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,23}$", var.name))
    error_message = "name must be 3-24 characters: lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "primary" {
  description = "Regional inputs for the primary region, from the primary regional-stack outputs."
  type = object({
    kms_key_arn          = string
    db_subnet_group_name = string
    db_security_group_id = string
  })

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:kms:[a-z0-9-]+:[0-9]{12}:key/", var.primary.kms_key_arn))
    error_message = "primary.kms_key_arn must be a KMS key ARN."
  }
}

variable "dr" {
  description = "Regional inputs for the DR region, from the DR regional-stack outputs."
  type = object({
    kms_key_arn          = string
    db_subnet_group_name = string
    db_security_group_id = string
  })

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:kms:[a-z0-9-]+:[0-9]{12}:key/", var.dr.kms_key_arn))
    error_message = "dr.kms_key_arn must be a KMS key ARN."
  }
}

# --- Aurora --------------------------------------------------------------------

variable "aurora_engine_version" {
  description = "Aurora PostgreSQL version (major.minor). Both regions run the same version; Global Database requires it."
  type        = string
  default     = "16.6"

  validation {
    condition     = can(regex("^1[5-7]\\.[0-9]+$", var.aurora_engine_version))
    error_message = "aurora_engine_version must be an Aurora PostgreSQL 15, 16 or 17 version, as major.minor."
  }
}

variable "aurora_instance_class" {
  description = "Instance class for both regions. The DR writer must handle full load after promotion, so it is not downsized by default."
  type        = string
  default     = "db.r7g.large"

  validation {
    condition     = can(regex("^db\\.(r[5-8]g?d?|x2g|t4g)\\.", var.aurora_instance_class))
    error_message = "aurora_instance_class must be a db.r*, db.x2g or db.t4g class supported by Aurora Global Database."
  }
}

variable "primary_instance_count" {
  description = "Aurora instances in the primary cluster (1 writer + readers)."
  type        = number
  default     = 2

  validation {
    condition     = var.primary_instance_count >= 1 && var.primary_instance_count <= 16
    error_message = "primary_instance_count must be between 1 and 16."
  }
}

variable "dr_instance_count" {
  description = "Aurora instances in the DR cluster. At least 1: a headless secondary is cheaper but can't be promoted until an instance is added, which adds minutes to the RTO."
  type        = number
  default     = 1

  validation {
    condition     = var.dr_instance_count >= 1 && var.dr_instance_count <= 16
    error_message = "dr_instance_count must be between 1 and 16 (no headless secondary in this design)."
  }
}

variable "database_name" {
  description = "Initial database name."
  type        = string
  default     = "orders"

  validation {
    condition     = can(regex("^[a-z][a-z0-9_]{0,62}$", var.database_name))
    error_message = "database_name must start with a letter and use lowercase letters, digits and underscores."
  }
}

variable "master_username" {
  description = "Aurora master username. The password is generated at apply time and written only to the cluster and the secret."
  type        = string
  default     = "orders_admin"

  validation {
    condition     = can(regex("^[a-z][a-z0-9_]{0,15}$", var.master_username)) && !contains(["postgres", "admin", "rdsadmin"], var.master_username)
    error_message = "master_username must be 1-16 lowercase characters and not a reserved name."
  }
}

variable "db_password_version" {
  description = "Bump to rotate the master password: a new value is generated and written to the cluster and the secret in the same apply."
  type        = number
  default     = 1

  validation {
    condition     = var.db_password_version >= 1 && floor(var.db_password_version) == var.db_password_version
    error_message = "db_password_version must be a positive integer."
  }
}

variable "backup_retention_days" {
  description = "Aurora automated backup retention (PITR window) in each cluster."
  type        = number
  default     = 14

  validation {
    condition     = var.backup_retention_days >= 7 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 7 and 35."
  }
}

variable "deletion_protection" {
  description = "Deletion protection on the global cluster and both regional clusters."
  type        = bool
  default     = true
}

# --- S3 ------------------------------------------------------------------------

variable "primary_bucket_name" {
  description = "Application bucket in the primary region."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.primary_bucket_name))
    error_message = "primary_bucket_name must be a valid S3 bucket name."
  }
}

variable "dr_bucket_name" {
  description = "Application bucket in the DR region (replication destination)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.dr_bucket_name))
    error_message = "dr_bucket_name must be a valid S3 bucket name."
  }
}

variable "s3_replication_time_control" {
  description = "Enable S3 Replication Time Control (99.99% of objects in 15 minutes, with metrics). Adds a per-GB charge."
  type        = bool
  default     = false
}

variable "s3_bidirectional_replication" {
  description = "Also replicate DR -> primary (with replica modification sync), so writes made after a failover flow back for failback."
  type        = bool
  default     = true
}

variable "noncurrent_version_expiration_days" {
  description = "Days to keep noncurrent object versions (the recovery window for overwrites and deletes)."
  type        = number
  default     = 30

  validation {
    condition     = var.noncurrent_version_expiration_days >= 1
    error_message = "noncurrent_version_expiration_days must be at least 1."
  }
}

# --- Secrets Manager -----------------------------------------------------------

variable "secret_name" {
  description = "Database secret name. The DR replica has the same name in the DR region, so the app config only changes the region."
  type        = string
  default     = "dr-app/aurora-master"

  validation {
    condition     = can(regex("^[A-Za-z0-9/_+=.@-]{1,256}$", var.secret_name))
    error_message = "secret_name must be a valid Secrets Manager name."
  }
}

# --- Route 53 ------------------------------------------------------------------

variable "dns" {
  description = <<-EOT
    Route 53 failover. Two-phase bootstrap: the ALBs are created by the AWS
    Load Balancer Controller when the chart is installed, so on the first apply
    leave primary_alb and dr_alb unset (no DNS resources are created). After
    both charts are installed, set them from each Ingress status and apply again.
  EOT
  type = object({
    hosted_zone_id = string
    record_name    = string
    primary_alb = optional(object({
      dns_name = string
      zone_id  = string
    }))
    dr_alb = optional(object({
      dns_name = string
      zone_id  = string
    }))
    health_check_path = optional(string, "/healthz/ready")
    request_interval  = optional(number, 30)
    failure_threshold = optional(number, 3)
  })
  default = null

  validation {
    condition     = var.dns == null || ((try(var.dns.primary_alb, null) == null) == (try(var.dns.dr_alb, null) == null))
    error_message = "Set both dns.primary_alb and dns.dr_alb, or neither (phase 1 of the bootstrap)."
  }

  validation {
    condition     = var.dns == null || contains([10, 30], try(var.dns.request_interval, 30))
    error_message = "dns.request_interval must be 10 or 30 seconds."
  }

  validation {
    condition     = var.dns == null || (try(var.dns.failure_threshold, 3) >= 1 && try(var.dns.failure_threshold, 3) <= 10)
    error_message = "dns.failure_threshold must be between 1 and 10."
  }

  validation {
    condition     = var.dns == null || startswith(try(var.dns.health_check_path, "/healthz/ready"), "/")
    error_message = "dns.health_check_path must start with /."
  }
}

# --- alarms --------------------------------------------------------------------

variable "replication_lag_alarm_seconds" {
  description = "Alarm when Aurora Global Database replication lag to the DR region exceeds this. Keep it at or below the failover CLI's planned-mode threshold."
  type        = number
  default     = 5

  validation {
    condition     = var.replication_lag_alarm_seconds > 0 && var.replication_lag_alarm_seconds <= 300
    error_message = "replication_lag_alarm_seconds must be between 0 and 300."
  }
}

variable "alarm_topic_arns" {
  description = "SNS topics notified by the replication and health alarms, keyed by region role. Empty = alarms without actions."
  type = object({
    primary = optional(list(string), [])
    dr      = optional(list(string), [])
  })
  default = {}
}

variable "tags" {
  description = "Extra tags (the providers' default_tags still apply)."
  type        = map(string)
  default     = {}
}
