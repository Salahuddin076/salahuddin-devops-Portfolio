provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "hybrid-cloud-fintech"
      ManagedBy   = "terraform"
      Environment = "reference"
    }
  }
}
