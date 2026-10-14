terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
  }

  # No backend block: validation only. Use a remote backend with locking
  # (S3 with use_lockfile) and one state per root before applying anything.
}
