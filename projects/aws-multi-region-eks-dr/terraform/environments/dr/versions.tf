terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
  }

  # No backend block, so validation needs no bucket. Use a remote backend with
  # locking per environment in real use, and keep each region's state in a
  # bucket in that region: during an outage the DR stack must be operable
  # without reading anything stored in the failed region.
}
