terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
  }

  # Local state by default (terraform.tfstate, git-ignored). Before a team
  # uses this, move state to a dedicated bucket in the management or a
  # tooling account, with versioning and S3-native locking:
  #
  # backend "s3" {
  #   bucket       = "example-lz-terraform-state"
  #   key          = "landing-zone/management/terraform.tfstate"
  #   region       = "us-east-1"
  #   encrypt      = true
  #   use_lockfile = true
  # }
}
