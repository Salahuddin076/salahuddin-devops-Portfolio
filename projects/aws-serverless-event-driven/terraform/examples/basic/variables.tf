variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.region))
    error_message = "region must look like an AWS region code, e.g. us-east-1."
  }
}

variable "project" {
  description = "Value for the project default tag."
  type        = string
  default     = "aws-serverless-event-driven"
}

variable "owner" {
  description = "Value for the owner default tag (team accountable for the stack)."
  type        = string
  default     = "platform-team"
}

variable "environment" {
  description = "Environment name; also part of every resource name."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "alarm_emails" {
  description = "Who receives operational alarms."
  type        = list(string)
  default     = ["oncall@example.com"]
}

variable "notification_emails" {
  description = "Who receives OrderAccepted notifications (demo only; a real consumer would subscribe a queue or a function)."
  type        = list(string)
  default     = []
}
