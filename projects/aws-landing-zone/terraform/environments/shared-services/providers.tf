# No credentials here. The caller's identity assumes the deployer role in
# the shared-services (network) account.
provider "aws" {
  region = var.region

  assume_role {
    role_arn     = var.network_role_arn
    session_name = "landing-zone-network"
  }

  default_tags {
    tags = {
      Project     = "aws-landing-zone"
      ManagedBy   = "terraform"
      Owner       = "platform-team"
      Environment = "shared"
      CostCenter  = var.cost_center
    }
  }
}
