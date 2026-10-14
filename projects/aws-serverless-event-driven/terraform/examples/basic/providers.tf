# Credentials come from the standard AWS SDK chain (env vars, SSO profile,
# instance role). Nothing is configured here on purpose.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project     = var.project
      owner       = var.owner
      environment = var.environment
      managed-by  = "terraform"
    }
  }
}
