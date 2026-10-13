variable "name_prefix" {
  description = "Prefix for every resource name (lowercase letters, digits, hyphens)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be 3-32 chars of lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget in USD."
  type        = number

  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be greater than 0."
  }
}

variable "actual_thresholds_pct" {
  description = "Budget percentages that trigger an ACTUAL-spend notification."
  type        = list(number)
  default     = [80, 100]

  validation {
    condition     = length(var.actual_thresholds_pct) > 0 && alltrue([for t in var.actual_thresholds_pct : t >= 1 && t <= 200])
    error_message = "Each actual threshold must be between 1 and 200 (percent)."
  }
}

variable "forecast_thresholds_pct" {
  description = "Budget percentages that trigger a FORECASTED-spend notification."
  type        = list(number)
  default     = [100]

  validation {
    condition     = alltrue([for t in var.forecast_thresholds_pct : t >= 1 && t <= 200])
    error_message = "Each forecast threshold must be between 1 and 200 (percent)."
  }
}

variable "notification_emails" {
  description = "Email addresses subscribed to the alerts SNS topic (each must confirm the subscription)."
  type        = list(string)

  validation {
    condition     = length(var.notification_emails) > 0 && alltrue([for e in var.notification_emails : can(regex("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$", e))])
    error_message = "notification_emails must contain at least one valid email address."
  }
}

variable "anomaly_impact_threshold_usd" {
  description = "Alert when an anomaly's total absolute impact is at least this many USD."
  type        = number
  default     = 50

  validation {
    condition     = var.anomaly_impact_threshold_usd >= 1
    error_message = "anomaly_impact_threshold_usd must be at least 1."
  }
}

variable "existing_anomaly_monitor_arn" {
  description = <<-EOT
    ARN of an existing Cost Anomaly Detection monitor to subscribe to. AWS allows
    only one AWS-services (DIMENSIONAL/SERVICE) monitor per account, so set this
    when the account already has one; leave null to create a new monitor.
  EOT
  type        = string
  default     = null

  validation {
    condition     = var.existing_anomaly_monitor_arn == null || can(regex("^arn:aws[a-z-]*:ce::[0-9]{12}:anomalymonitor/", var.existing_anomaly_monitor_arn))
    error_message = "existing_anomaly_monitor_arn must be a Cost Explorer anomaly monitor ARN."
  }
}

variable "create_data_export" {
  description = "Create the FOCUS 1.0 data export (BCM Data Exports) and its S3 bucket."
  type        = bool
  default     = true
}

variable "export_retention_days" {
  description = "Days to keep export objects before expiry. Keep >= 400 to allow year-over-year comparisons."
  type        = number
  default     = 400

  validation {
    condition     = var.export_retention_days >= 30 && var.export_retention_days <= 3650
    error_message = "export_retention_days must be between 30 and 3650."
  }
}

variable "export_s3_prefix" {
  description = "Key prefix inside the bucket where exports are delivered."
  type        = string
  default     = "focus"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9/_-]*[a-z0-9]$", var.export_s3_prefix))
    error_message = "export_s3_prefix must be lowercase alphanumerics, '/', '_' or '-', without leading/trailing slashes."
  }
}

variable "force_destroy_bucket" {
  description = "Allow terraform destroy to delete a non-empty export bucket. Keep false outside sandboxes."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Extra tags merged onto resources (provider default_tags still apply)."
  type        = map(string)
  default     = {}
}
