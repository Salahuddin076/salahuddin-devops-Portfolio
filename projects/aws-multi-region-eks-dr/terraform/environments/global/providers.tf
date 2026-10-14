# Two aliased providers feed the global-data module's configuration_aliases.
# Credentials come from the standard AWS SDK chain; nothing is configured here.

locals {
  default_tags = {
    project    = "aws-multi-region-eks-dr"
    app        = var.app_name
    layer      = "global"
    managed-by = "terraform"
    owner      = var.owner
  }
}

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
