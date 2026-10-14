# Shared lookups and names. Account ID, region and partition come from the
# caller's credentials at plan time; nothing account-specific is hardcoded.

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_region" "current" {}

data "aws_region" "us_east_1" {
  provider = aws.us_east_1
}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  bucket_name = coalesce(var.bucket_name, "${var.name_prefix}-origin-${local.account_id}-${data.aws_region.current.region}")

  primary_domain = var.domain_names[0]
  san_domains    = slice(var.domain_names, 1, length(var.domain_names))

  # One A and one AAAA alias per hostname (the distribution has IPv6 on).
  alias_records = merge([
    for d in var.domain_names : {
      "${d}/A"    = { name = d, type = "A" }
      "${d}/AAAA" = { name = d, type = "AAAA" }
    }
  ]...)

  logging_enabled = var.access_logs != null

  tags = merge(var.tags, { module = "static-site" })
}

# The aws.us_east_1 alias exists only because CloudFront reads ACM
# certificates and log deliveries from us-east-1. Passing a provider in any
# other region fails late (at apply) with an unhelpful error, so fail at plan.
check "us_east_1_alias_region" {
  assert {
    condition     = data.aws_region.us_east_1.region == "us-east-1"
    error_message = "The aws.us_east_1 provider passed to the static-site module must be configured with region = \"us-east-1\"."
  }
}
