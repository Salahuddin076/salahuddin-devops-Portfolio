variable "project" {
  description = "Value for the project default tag."
  type        = string
  default     = "finops-cost-optimization"
}

variable "owner" {
  description = "Value for the owner default tag (team or person accountable for the spend)."
  type        = string
  default     = "platform-team"
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget in USD."
  type        = number
  default     = 6500
}

variable "notification_emails" {
  description = "Recipients of budget and anomaly alerts."
  type        = list(string)
  default     = ["finops-alerts@example.com"]
}
