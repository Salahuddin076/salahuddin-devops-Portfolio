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
  default     = "aws-codepipeline-container-delivery"
}

variable "owner" {
  description = "Value for the owner default tag (team accountable for the stack)."
  type        = string
  default     = "platform-team"
}

variable "repository_full_id" {
  description = "GitHub repository (owner/name) the pipeline builds."
  type        = string
  default     = "example-org/container-delivery-demo"
}

variable "vpc_id" {
  description = "Existing VPC ID."
  type        = string
}

variable "subnet_ids" {
  description = "Existing private subnet IDs (two or more AZs)."
  type        = list(string)
}

variable "approval_emails" {
  description = "Who approves prod releases."
  type        = list(string)
  default     = ["release-approvers@example.com"]
}

variable "first_apply" {
  description = "True for the first apply: services start at desired_count 0 until the pipeline has pushed a real image (docs/operations.md)."
  type        = bool
  default     = true
}
