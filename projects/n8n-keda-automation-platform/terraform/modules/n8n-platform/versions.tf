terraform {
  # 1.11 for write-only arguments (auth_token_wo) fed by an ephemeral read.
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
  }
}
