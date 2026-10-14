variable "region" {
  description = "AWS region of the existing EKS cluster."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.region))
    error_message = "region must look like us-east-1."
  }
}

variable "environment" {
  description = "Environment tag value."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "cluster_name" {
  description = "Existing EKS cluster to install the CSI driver add-on into."
  type        = string
  default     = "example-eks"
}

variable "rotation_lambda_arn" {
  description = "Existing rotation Lambda for the DB secret, or null to leave rotation off."
  type        = string
  default     = null
}
