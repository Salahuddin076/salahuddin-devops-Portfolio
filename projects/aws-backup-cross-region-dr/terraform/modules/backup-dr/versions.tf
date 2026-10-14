terraform {
  # 1.9+ for variable validations that reference other variables
  # (vault lock min <= max, retentions inside the lock range).
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source                = "hashicorp/aws"
      version               = ">= 6.0, < 7.0"
      configuration_aliases = [aws.primary, aws.dr]
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4, < 3.0"
    }
  }
}
