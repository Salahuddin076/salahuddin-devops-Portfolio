variable "app_name" {
  description = "Application name; must match the regional environments."
  type        = string
  default     = "dr-app"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,7}$", var.app_name))
    error_message = "app_name must be 3-8 lowercase characters."
  }
}

variable "owner" {
  description = "Owner tag value."
  type        = string
  default     = "platform-team"
}

variable "primary_region" {
  description = "Primary region (Aurora writer, PRIMARY failover record at bootstrap)."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.primary_region))
    error_message = "primary_region must be an AWS region name."
  }
}

variable "dr_region" {
  description = "DR region (Aurora secondary, SECONDARY failover record at bootstrap)."
  type        = string
  default     = "us-west-2"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.dr_region))
    error_message = "dr_region must be an AWS region name."
  }

  validation {
    condition     = var.dr_region != var.primary_region
    error_message = "dr_region must differ from primary_region."
  }
}

variable "primary" {
  description = "global_data_inputs output of environments/primary."
  type = object({
    kms_key_arn          = string
    db_subnet_group_name = string
    db_security_group_id = string
  })
}

variable "dr" {
  description = "global_data_inputs output of environments/dr."
  type = object({
    kms_key_arn          = string
    db_subnet_group_name = string
    db_security_group_id = string
  })
}

variable "aurora_engine_version" {
  description = "Aurora PostgreSQL version."
  type        = string
  default     = "16.6"
}

variable "aurora_instance_class" {
  description = "Aurora instance class in both regions."
  type        = string
  default     = "db.r7g.large"
}

variable "primary_instance_count" {
  description = "Aurora instances in the primary region."
  type        = number
  default     = 2
}

variable "dr_instance_count" {
  description = "Aurora instances in the DR region (at least 1)."
  type        = number
  default     = 1
}

variable "db_password_version" {
  description = "Bump to rotate the master password."
  type        = number
  default     = 1
}

variable "s3_replication_time_control" {
  description = "Enable S3 Replication Time Control."
  type        = bool
  default     = false
}

variable "dns" {
  description = "Route 53 failover inputs; leave the ALBs unset on the first apply (see the module variable)."
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
}

variable "replication_lag_alarm_seconds" {
  description = "Aurora replication lag alarm threshold in seconds."
  type        = number
  default     = 5
}

variable "alarm_topic_arns" {
  description = "SNS topics for alarms, by region role."
  type = object({
    primary = optional(list(string), [])
    dr      = optional(list(string), [])
  })
  default = {}
}
