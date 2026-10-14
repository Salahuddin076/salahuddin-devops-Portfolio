# Credentials come from the standard AWS SDK chain. Nothing is configured here.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project    = "ecs-fargate-blue-green"
      owner      = var.owner
      managed-by = "terraform"
    }
  }
}
