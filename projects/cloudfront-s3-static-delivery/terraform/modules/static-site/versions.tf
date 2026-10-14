terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
      # aws         : the origin bucket's region (CloudFront itself is global).
      # aws.us_east_1: the ACM certificate and the CloudFront access-log
      #                delivery, both of which CloudFront only accepts from
      #                us-east-1.
      configuration_aliases = [aws.us_east_1]
    }
  }
}
