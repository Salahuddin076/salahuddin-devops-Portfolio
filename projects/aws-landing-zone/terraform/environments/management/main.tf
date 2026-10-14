# Management account composition: organization, guardrails, Identity Center
# and the log archive.
#
# The SCP attachment map and the region allow-list values are read from
# policy/, so policy/check_scps.py and policy/simulate_scp.py check exactly
# what is deployed.

locals {
  policy_dir      = "${path.module}/../../../policy"
  attachment_map  = jsondecode(file("${local.policy_dir}/attachments.json"))
  template_values = jsondecode(file("${local.policy_dir}/template-values.json"))

  default_tags = {
    Project     = "aws-landing-zone"
    ManagedBy   = "terraform"
    Owner       = "platform-team"
    Environment = "shared"
    CostCenter  = var.cost_center
  }
}

check "home_region_is_allowed" {
  assert {
    condition     = contains(local.template_values.allowed_regions, var.region)
    error_message = "Home region ${var.region} is not in the SCP region allow-list (policy/template-values.json)."
  }
}

module "organization" {
  source = "../../modules/organization"

  accounts                     = var.accounts
  delegated_administrators     = var.delegated_administrators
  security_tooling_account_key = var.security_tooling_account_key
}

module "guardrails" {
  source = "../../modules/guardrails"

  target_ids            = module.organization.ou_ids
  attachments           = local.attachment_map.attachments
  allowed_regions       = local.template_values.allowed_regions
  exempt_principal_arns = local.template_values.exempt_principal_arns
  tag_policy_targets    = ["root"]
}

module "identity_center" {
  source = "../../modules/identity-center"

  group_ids   = var.identity_center_group_ids
  account_ids = merge(module.organization.account_ids, { management = module.organization.management_account_id })
  assignments = var.identity_center_assignments
}

module "log_archive" {
  source = "../../modules/log-archive"

  providers = {
    aws.management  = aws
    aws.log_archive = aws.log_archive
  }

  organization_id            = module.organization.organization_id
  bucket_name                = var.log_bucket_name
  object_lock_retention_days = var.object_lock_retention_days
}
