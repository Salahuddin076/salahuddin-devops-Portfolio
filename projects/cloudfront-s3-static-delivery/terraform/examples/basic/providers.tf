# Credentials come from the standard AWS SDK chain (env vars, SSO profile,
# instance role). Nothing is configured here on purpose.
locals {
  default_tags = {
    project    = var.project
    owner      = var.owner
    managed-by = "terraform"
  }
}

# The bucket's region.
provider "aws" {
  region = var.region

  default_tags {
    tags = local.default_tags
  }
}

# CloudFront's certificate and log delivery must be in us-east-1, whatever
# var.region is.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = local.default_tags
  }
}
