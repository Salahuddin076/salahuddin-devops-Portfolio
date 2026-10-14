# Minimal caller so the module validates on its own: the module declares
# configuration_aliases (aws.primary, aws.dr), which only a caller can
# supply. Region-only providers, no credentials. `terraform validate` only;
# never planned or applied.

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4, < 3.0"
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

locals {
  policy = jsondecode(file("${path.module}/../../../../policy/backup-policy.json"))
}

module "backup_dr" {
  source = "../"
  providers = {
    aws.primary = aws.primary
    aws.dr      = aws.dr
  }

  name_prefix                    = "harness"
  backup_plans                   = local.policy.plans
  selection_tag_key              = local.policy.selection_tag_key
  vault_lock_mode                = local.policy.vault_lock.mode
  vault_lock_min_retention_days  = local.policy.vault_lock.min_retention_days
  vault_lock_max_retention_days  = local.policy.vault_lock.max_retention_days
  vault_lock_changeable_for_days = local.policy.vault_lock.changeable_for_days
  break_glass_role_arn           = "arn:aws:iam::123456789012:role/backup-break-glass"

  restore_testing = {
    selections = {
      rds_gold = { resource_type = "RDS" }
    }
  }
  audit_framework = { enabled = true }
}

output "dr_vault_arn" {
  description = "DR vault ARN from the module."
  value       = module.backup_dr.dr_vault_arn
}
