terraform {
  # 1.11+ for the write-only database password arguments in global-data.
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
  }

  # No backend block, so validation needs no bucket. In real use keep this
  # state in the DR region (or replicate it there): the global layer is what
  # you need to change during a primary-region outage.
}
