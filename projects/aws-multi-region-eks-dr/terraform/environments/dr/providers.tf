# Credentials come from the standard AWS SDK chain (env vars, SSO profile,
# CI OIDC role). Nothing is configured here on purpose.

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project     = "aws-multi-region-eks-dr"
      app         = var.app_name
      region-role = local.role
      managed-by  = "terraform"
      owner       = var.owner
    }
  }
}
