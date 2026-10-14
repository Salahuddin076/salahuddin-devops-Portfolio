# No credentials here. The caller's identity (SSO profile, CI OIDC role)
# assumes a deployer role in each account; the role ARNs are variables.

# Management account: organization, guardrails, Identity Center, org trail.
provider "aws" {
  region = var.region

  assume_role {
    role_arn     = var.management_role_arn
    session_name = "landing-zone-management"
  }

  default_tags {
    tags = local.default_tags
  }
}

# Log-archive account: central bucket, KMS key, Config aggregator. This
# account is created by this same configuration, so the first apply targets
# module.organization only (see docs/operations.md, bootstrap order).
provider "aws" {
  alias  = "log_archive"
  region = var.region

  assume_role {
    role_arn     = var.log_archive_role_arn
    session_name = "landing-zone-log-archive"
  }

  default_tags {
    tags = local.default_tags
  }
}
