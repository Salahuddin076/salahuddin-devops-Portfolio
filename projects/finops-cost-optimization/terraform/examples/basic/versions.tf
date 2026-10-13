terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # No backend block: state stays local (terraform.tfstate, git-ignored).
  # Use a remote backend with locking before sharing this with a team.
}
