# No credentials here. The provider uses the standard chain (SSO profile,
# environment, or a CI role). This example has only ever been validated.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "n8n-keda-automation-platform"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "platform-team"
    }
  }
}
