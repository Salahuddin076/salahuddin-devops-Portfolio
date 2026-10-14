data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.region

  source_dir = coalesce(var.lambda_source_dir, "${path.module}/../../../src")

  ingest_name  = "${var.name_prefix}-ingest"
  process_name = "${var.name_prefix}-process"

  # AWS guidance: visibility timeout of at least 6x the function timeout plus
  # the batching window, so a message is not redelivered while still in flight.
  visibility_timeout_seconds = 6 * var.processor_timeout_seconds + var.batching_window_seconds

  event_source = "com.example.orders"
}
