variable "name_prefix" {
  description = "Prefix for every resource name, e.g. orders-dev. Lowercase letters, digits and hyphens."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,23}$", var.name_prefix))
    error_message = "name_prefix must be 3-24 characters: a lowercase letter followed by lowercase letters, digits or hyphens."
  }
}

variable "lambda_source_dir" {
  description = "Directory holding the handler modules (ingest.py, process.py, ...). Defaults to the project's src/."
  type        = string
  default     = null
}

variable "lambda_memory_mb" {
  description = "Memory for both functions. CPU scales with memory on Lambda."
  type        = number
  default     = 256

  validation {
    condition     = var.lambda_memory_mb >= 128 && var.lambda_memory_mb <= 10240
    error_message = "lambda_memory_mb must be between 128 and 10240."
  }
}

variable "processor_timeout_seconds" {
  description = "Processor Lambda timeout. The queue visibility timeout is derived from it (6x plus the batching window)."
  type        = number
  default     = 30

  validation {
    condition     = var.processor_timeout_seconds >= 3 && var.processor_timeout_seconds <= 900
    error_message = "processor_timeout_seconds must be between 3 and 900."
  }
}

variable "processor_reserved_concurrency" {
  description = "Reserved concurrency for the processor: caps the load it can put on DynamoDB and EventBridge, and guarantees it capacity."
  type        = number
  default     = 10

  validation {
    condition     = var.processor_reserved_concurrency >= 2 && var.processor_reserved_concurrency <= 1000
    error_message = "processor_reserved_concurrency must be between 2 and 1000."
  }
}

variable "processor_max_concurrency" {
  description = "Event source mapping maximum concurrency. Keep it at or below reserved concurrency so SQS polling never causes throttles."
  type        = number
  default     = 10

  validation {
    condition     = var.processor_max_concurrency >= 2 && var.processor_max_concurrency <= 1000
    error_message = "processor_max_concurrency must be between 2 and 1000 (the event source mapping minimum is 2)."
  }
}

variable "batch_size" {
  description = "SQS messages per processor invocation."
  type        = number
  default     = 10

  validation {
    condition     = var.batch_size >= 1 && var.batch_size <= 10
    error_message = "batch_size must be between 1 and 10 (larger batches need a batching window and are not needed here)."
  }
}

variable "batching_window_seconds" {
  description = "How long the event source mapping waits to fill a batch."
  type        = number
  default     = 1

  validation {
    condition     = var.batching_window_seconds >= 0 && var.batching_window_seconds <= 300
    error_message = "batching_window_seconds must be between 0 and 300."
  }
}

variable "max_receive_count" {
  description = "Deliveries before SQS moves a message to the dead-letter queue."
  type        = number
  default     = 5

  validation {
    condition     = var.max_receive_count >= 1 && var.max_receive_count <= 1000
    error_message = "max_receive_count must be between 1 and 1000."
  }
}

variable "queue_retention_seconds" {
  description = "Main queue message retention. The DLQ keeps messages for the 14-day maximum, which must exceed this."
  type        = number
  default     = 345600

  validation {
    condition     = var.queue_retention_seconds >= 3600 && var.queue_retention_seconds <= 604800
    error_message = "queue_retention_seconds must be between 3600 (1 hour) and 604800 (7 days)."
  }
}

variable "idempotency_ttl_hours" {
  description = "How long an idempotency record is kept, i.e. the window in which a retried request is recognised."
  type        = number
  default     = 24

  validation {
    condition     = var.idempotency_ttl_hours >= 1 && var.idempotency_ttl_hours <= 720
    error_message = "idempotency_ttl_hours must be between 1 and 720."
  }
}

variable "api_throttle_rate_limit" {
  description = "Steady-state requests per second allowed on the API stage."
  type        = number
  default     = 50

  validation {
    condition     = var.api_throttle_rate_limit > 0 && var.api_throttle_rate_limit <= 10000
    error_message = "api_throttle_rate_limit must be between 1 and 10000."
  }
}

variable "api_throttle_burst_limit" {
  description = "Burst capacity on the API stage."
  type        = number
  default     = 100

  validation {
    condition     = var.api_throttle_burst_limit >= 1 && var.api_throttle_burst_limit <= 5000
    error_message = "api_throttle_burst_limit must be between 1 and 5000."
  }
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the function and API access logs."
  type        = number
  default     = 14

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be a value CloudWatch Logs accepts (1, 3, 5, 7, 14, 30, 60, 90, ...)."
  }
}

variable "log_level" {
  description = "Handler log level."
  type        = string
  default     = "INFO"

  validation {
    condition     = contains(["DEBUG", "INFO", "WARNING", "ERROR"], var.log_level)
    error_message = "log_level must be DEBUG, INFO, WARNING or ERROR."
  }
}

variable "oldest_message_age_alarm_seconds" {
  description = "Alarm when the oldest message in the main queue is older than this (processing is falling behind)."
  type        = number
  default     = 300

  validation {
    condition     = var.oldest_message_age_alarm_seconds >= 60
    error_message = "oldest_message_age_alarm_seconds must be at least 60."
  }
}

variable "notification_emails" {
  description = "Email subscribers to the OrderAccepted notifications topic (each must confirm)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for e in var.notification_emails : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", e))])
    error_message = "notification_emails must contain valid email addresses."
  }
}

variable "alarm_emails" {
  description = "Email subscribers to the operational alarms topic (each must confirm)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for e in var.alarm_emails : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", e))])
    error_message = "alarm_emails must contain valid email addresses."
  }
}

variable "table_deletion_protection" {
  description = "Protect the orders table from accidental deletion. Set false only for throwaway environments."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Extra tags for module resources (provider default_tags still apply)."
  type        = map(string)
  default     = {}
}
