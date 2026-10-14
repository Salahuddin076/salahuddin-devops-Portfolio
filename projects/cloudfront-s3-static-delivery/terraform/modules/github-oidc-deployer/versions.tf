terraform {
  # 1.9+ for the variable validation that references another variable
  # (an existing provider ARN is required when none is created).
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
  }
}
