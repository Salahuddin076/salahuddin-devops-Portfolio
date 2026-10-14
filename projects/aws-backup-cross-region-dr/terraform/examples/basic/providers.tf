# Credentials come from the standard AWS SDK chain (env vars, SSO profile,
# instance role). Nothing is configured here on purpose.
#
# Cross-account DR: add an assume_role block to the "dr" provider pointing
# at a role in the recovery account. The module detects the different
# account and adds the cross-account vault and key permissions.

provider "aws" {
  alias  = "primary"
  region = var.primary_region

  default_tags {
    tags = local.default_tags
  }
}

provider "aws" {
  alias  = "dr"
  region = var.dr_region

  default_tags {
    tags = local.default_tags
  }
}
