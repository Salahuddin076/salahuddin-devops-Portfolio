# Validation harness only: never planned or applied.
#
# A module that declares configuration_aliases cannot be validated on its
# own ("Provider configuration not present"), so CI validates it through
# this caller. The provider blocks carry a region and nothing else: validate
# does not contact AWS.

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
  alias  = "management"
  region = "us-east-1"
}

provider "aws" {
  alias  = "log_archive"
  region = "us-east-1"
}

module "log_archive" {
  source = "../"

  providers = {
    aws.management  = aws.management
    aws.log_archive = aws.log_archive
  }

  organization_id = "o-exampleorg1"
  bucket_name     = "example-lz-org-logs"
}
