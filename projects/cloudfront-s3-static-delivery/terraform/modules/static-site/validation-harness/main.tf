# Minimal caller so the static-site module validates on its own: the module
# declares configuration_aliases (aws.us_east_1), which only a caller can
# supply. Region-only providers, no credentials, documentation-safe values.
# `terraform validate` only; never planned or applied.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
  }
}

provider "aws" {
  region = "eu-west-1"
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

module "static_site" {
  source = "../"
  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  name_prefix    = "harness"
  domain_names   = ["example.com", "www.example.com"]
  hosted_zone_id = "Z0123456789EXAMPLE0AB"
  price_class    = "PriceClass_100"

  # Exercise the optional paths too.
  web_acl_arn = "arn:aws:wafv2:us-east-1:123456789012:global/webacl/harness-edge/a1b2c3d4-5678-90ab-cdef-0123456789ab"
  kms_key_arn = "arn:aws:kms:eu-west-1:123456789012:key/a1b2c3d4-5678-90ab-cdef-ba9876543210"
  access_logs = { retention_days = 14 }
}

output "distribution_arn" {
  description = "Distribution ARN from the module."
  value       = module.static_site.distribution_arn
}
