# Minimal caller so global-data validates on its own: the module declares
# configuration_aliases (aws.primary, aws.dr), which only a caller can supply.
# Region-only providers, no credentials, placeholder ARNs and IDs. Phase-2 DNS
# inputs are set so the Route 53 resources are type-checked too.
# `terraform validate` only; never planned or applied.

terraform {
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
  }
}

provider "aws" {
  alias  = "primary"
  region = "us-east-1"
}

provider "aws" {
  alias  = "dr"
  region = "us-west-2"
}

module "global_data" {
  source = "../"
  providers = {
    aws.primary = aws.primary
    aws.dr      = aws.dr
  }

  name = "harness"

  primary = {
    kms_key_arn          = "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-4000-8000-000000000001"
    db_subnet_group_name = "harness-use1-aurora"
    db_security_group_id = "sg-0123456789abcdef0"
  }
  dr = {
    kms_key_arn          = "arn:aws:kms:us-west-2:123456789012:key/00000000-0000-4000-8000-000000000002"
    db_subnet_group_name = "harness-usw2-aurora"
    db_security_group_id = "sg-0fedcba9876543210"
  }

  primary_bucket_name         = "example-harness-data-us-east-1"
  dr_bucket_name              = "example-harness-data-us-west-2"
  s3_replication_time_control = true

  dns = {
    hosted_zone_id = "Z0000000EXAMPLE"
    record_name    = "orders.example.com"
    primary_alb = {
      dns_name = "k8s-orders-example-0000000000.us-east-1.elb.amazonaws.com"
      zone_id  = "Z35SXDOTRQ7X7K"
    }
    dr_alb = {
      dns_name = "k8s-orders-example-1111111111.us-west-2.elb.amazonaws.com"
      zone_id  = "Z1H1FL5HABSF5"
    }
  }
}

output "failover_config" {
  description = "Failover CLI config from the module."
  value       = module.global_data.failover_config
}
