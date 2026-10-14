# CloudFront standard logging v2 to CloudWatch Logs (optional).
#
# Why v2 to CloudWatch rather than legacy logging to an S3 bucket: legacy
# CloudFront logging writes with an ACL grant, so its bucket must have ACLs
# enabled, which contradicts BucketOwnerEnforced everywhere else in this
# design. v2 delivery uses a resource policy instead, has field selection
# and JSON output, and the log group gives retention and Logs Insights
# queries with no extra pipeline. At high volume, a v2 delivery to S3 (or
# Firehose) is cheaper; that is a one-resource swap of the destination.
#
# All three delivery resources and the log group live in us-east-1: the
# delivery source for a CloudFront distribution must be created there.

resource "aws_cloudwatch_log_group" "access" {
  count    = local.logging_enabled ? 1 : 0
  provider = aws.us_east_1

  # /aws/vendedlogs/ is the prefix AWS recommends for vended log delivery
  # (it avoids the per-account log resource policy size limit).
  name              = "/aws/vendedlogs/cloudfront/${var.name_prefix}"
  retention_in_days = var.access_logs.retention_days
  tags              = local.tags
}

data "aws_iam_policy_document" "log_delivery" {
  count = local.logging_enabled ? 1 : 0

  statement {
    sid       = "AllowCloudFrontLogDelivery"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.access[0].arn}:log-stream:*"]

    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:logs:us-east-1:${local.account_id}:delivery-source:*"]
    }
  }
}

resource "aws_cloudwatch_log_resource_policy" "log_delivery" {
  count    = local.logging_enabled ? 1 : 0
  provider = aws.us_east_1

  policy_name     = "${var.name_prefix}-cloudfront-log-delivery"
  policy_document = data.aws_iam_policy_document.log_delivery[0].json
}

resource "aws_cloudwatch_log_delivery_source" "access" {
  count    = local.logging_enabled ? 1 : 0
  provider = aws.us_east_1

  name         = "${var.name_prefix}-cloudfront-access"
  log_type     = "ACCESS_LOGS"
  resource_arn = aws_cloudfront_distribution.this.arn
  tags         = local.tags
}

resource "aws_cloudwatch_log_delivery_destination" "access" {
  count    = local.logging_enabled ? 1 : 0
  provider = aws.us_east_1

  name          = "${var.name_prefix}-cloudfront-access-cwl"
  output_format = "json"

  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.access[0].arn
  }

  tags = local.tags
}

resource "aws_cloudwatch_log_delivery" "access" {
  count    = local.logging_enabled ? 1 : 0
  provider = aws.us_east_1

  delivery_source_name     = aws_cloudwatch_log_delivery_source.access[0].name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.access[0].arn

  tags = local.tags

  depends_on = [aws_cloudwatch_log_resource_policy.log_delivery]
}
