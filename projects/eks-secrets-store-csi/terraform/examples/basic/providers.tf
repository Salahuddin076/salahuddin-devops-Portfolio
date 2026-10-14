# No credentials here. The provider uses the standard chain (SSO profile,
# environment, or the CI role). This example has only ever been validated.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "eks-secrets-store-csi"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "platform-team"
    }
  }
}
