terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
      # The caller passes both: the org trail is created in the management
      # account, the bucket, key and aggregator in the log-archive account.
      configuration_aliases = [aws.management, aws.log_archive]
    }
  }
}
