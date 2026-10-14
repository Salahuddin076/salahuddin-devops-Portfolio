terraform {
  # 1.11+ for write-only arguments (master_password_wo, secret_string_wo) fed
  # from an ephemeral resource, so the database password never enters state.
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source                = "hashicorp/aws"
      version               = ">= 6.0, < 7.0"
      configuration_aliases = [aws.primary, aws.dr]
    }
  }
}
