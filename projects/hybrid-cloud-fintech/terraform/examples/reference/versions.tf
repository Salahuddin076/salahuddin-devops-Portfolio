terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
  }

  # Local state by default (terraform.tfstate, git-ignored). This example
  # exists to be validated (`terraform validate`), never applied against a
  # real account -- see the repository CLAUDE.md and this project's README.
}
