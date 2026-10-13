# Credentials come from the standard AWS SDK chain (env vars, SSO profile,
# instance role). Nothing is configured here on purpose.
provider "aws" {
  # Budgets, Cost Anomaly Detection and BCM Data Exports are served from us-east-1.
  region = "us-east-1"

  default_tags {
    tags = {
      project    = var.project
      owner      = var.owner
      managed-by = "terraform"
    }
  }
}
