# No credentials here. The caller's identity assumes a role in the target
# workload account (OrganizationAccountAccessRole right after vending, a
# narrower pipeline role afterwards).
provider "aws" {
  region = var.region

  assume_role {
    role_arn     = var.workload_role_arn
    session_name = "landing-zone-baseline"
  }

  default_tags {
    tags = {
      Project     = "aws-landing-zone"
      ManagedBy   = "terraform"
      Owner       = var.owner
      Environment = var.environment
      CostCenter  = var.cost_center
    }
  }
}
