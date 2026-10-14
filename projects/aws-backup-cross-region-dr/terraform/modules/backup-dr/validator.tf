# The restore validator Lambda (src/restore_validator) in the DR region. An
# EventBridge rule sends every completed restore job to it; the function
# validates only jobs created by a restore testing plan and reports the
# verdict with PutRestoreValidationResult.

locals {
  validator_enabled = var.restore_testing.enabled && var.restore_validator.enabled
  validator_name    = "${var.name_prefix}-restore-validator"
  validator_in_vpc  = length(var.restore_validator.subnet_ids) > 0
  validator_types   = toset([for s in values(var.restore_testing.selections) : s.resource_type if contains(["RDS", "DynamoDB", "S3", "EBS"], s.resource_type)])
  dr_region         = data.aws_region.dr.region
}

# boto3 ships with the runtime; the package is the standard-library source only.
data "archive_file" "validator" {
  count = local.validator_enabled ? 1 : 0

  type        = "zip"
  source_dir  = "${path.module}/../../../src/restore_validator"
  output_path = "${path.root}/.build/${local.validator_name}.zip"
  excludes    = ["__pycache__"]
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "validator" {
  provider = aws.dr
  count    = local.validator_enabled ? 1 : 0

  name               = local.validator_name
  description        = "Restore validator Lambda: read restored test resources, report validation results."
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = var.tags
}

data "aws_iam_policy_document" "validator" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:${local.partition}:logs:${local.dr_region}:${local.dr_acct}:log-group:/aws/lambda/${local.validator_name}:*"]
  }

  statement {
    sid       = "RestoreJobs"
    actions   = ["backup:DescribeRestoreJob", "backup:PutRestoreValidationResult"]
    resources = ["*"]
  }

  # Restored resource names are generated per test, so reads are scoped by
  # account and region rather than by name. All read-only.
  statement {
    sid = "ReadRestoredResources"
    actions = [
      "rds:DescribeDBInstances",
      "rds:ListTagsForResource",
      "dynamodb:Scan",
      "dynamodb:ListTagsOfResource",
      "ec2:DescribeVolumes",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "ReadRestoredBuckets"
    actions   = ["s3:ListBucket", "s3:GetObject", "s3:GetObjectVersion", "s3:GetBucketTagging"]
    resources = ["arn:${local.partition}:s3:::*"]
  }

  statement {
    sid       = "DecryptRestoredData"
    actions   = ["kms:Decrypt"]
    resources = [module.dr_vault.kms_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${local.dr_region}.amazonaws.com", "dynamodb.${local.dr_region}.amazonaws.com"]
    }
  }

  # Early cleanup only: delete rights exist solely for resources carrying
  # the restore-testing tag. The function checks the same tag first.
  dynamic "statement" {
    for_each = var.restore_validator.early_cleanup ? [1] : []

    content {
      sid       = "DeleteTaggedTestResourcesOnly"
      actions   = ["rds:DeleteDBInstance", "dynamodb:DeleteTable", "ec2:DeleteVolume"]
      resources = ["*"]

      condition {
        test     = "Null"
        variable = "aws:ResourceTag/${var.restore_validator.restore_test_tag_key}"
        values   = ["false"]
      }
    }
  }
}

resource "aws_iam_role_policy" "validator" {
  provider = aws.dr
  count    = local.validator_enabled ? 1 : 0

  name   = "restore-validation"
  role   = aws_iam_role.validator[0].id
  policy = data.aws_iam_policy_document.validator.json
}

resource "aws_iam_role_policy_attachment" "validator_vpc" {
  provider = aws.dr
  count    = local.validator_enabled && local.validator_in_vpc ? 1 : 0

  role       = aws_iam_role.validator[0].name
  policy_arn = "${local.managed_policy_prefix}/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "validator" {
  provider = aws.dr
  count    = local.validator_enabled ? 1 : 0

  name              = "/aws/lambda/${local.validator_name}"
  retention_in_days = var.restore_validator.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_function" "validator" {
  provider = aws.dr
  count    = local.validator_enabled ? 1 : 0

  function_name    = local.validator_name
  description      = "Validates AWS Backup restore-testing jobs and reports SUCCESSFUL/FAILED."
  role             = aws_iam_role.validator[0].arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.validator[0].output_path
  source_code_hash = data.archive_file.validator[0].output_base64sha256
  timeout          = 300
  memory_size      = 256

  environment {
    variables = {
      RESTORE_TEST_TAG_KEY = var.restore_validator.restore_test_tag_key
      DYNAMODB_MIN_ITEMS   = tostring(var.restore_validator.dynamodb_min_items)
      S3_MIN_OBJECTS       = tostring(var.restore_validator.s3_min_objects)
      S3_CHECKSUM_SAMPLE   = tostring(var.restore_validator.s3_checksum_sample)
      RDS_ROW_COUNT_QUERY  = var.restore_validator.rds_row_count_query
      EARLY_CLEANUP        = tostring(var.restore_validator.early_cleanup)
      METRIC_NAMESPACE     = "BackupDR/RestoreTesting"
    }
  }

  dynamic "vpc_config" {
    for_each = local.validator_in_vpc ? [1] : []

    content {
      subnet_ids         = var.restore_validator.subnet_ids
      security_group_ids = var.restore_validator.security_group_ids
    }
  }

  tags       = var.tags
  depends_on = [aws_cloudwatch_log_group.validator, aws_iam_role_policy.validator]
}

resource "aws_cloudwatch_event_rule" "restore_completed" {
  provider = aws.dr
  count    = local.validator_enabled ? 1 : 0

  name        = "${var.name_prefix}-restore-completed"
  description = "Completed AWS Backup restore jobs to the restore validator."
  event_pattern = jsonencode({
    source        = ["aws.backup"]
    "detail-type" = ["Restore Job State Change"]
    detail        = { status = ["COMPLETED"] }
  })
  tags = var.tags
}

resource "aws_cloudwatch_event_target" "restore_completed" {
  provider = aws.dr
  count    = local.validator_enabled ? 1 : 0

  rule      = aws_cloudwatch_event_rule.restore_completed[0].name
  target_id = "restore-validator"
  arn       = aws_lambda_function.validator[0].arn

  # The verdict must land inside the validation window; retry briefly, not for a day.
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 4
  }
}

resource "aws_lambda_permission" "events" {
  provider = aws.dr
  count    = local.validator_enabled ? 1 : 0

  statement_id  = "AllowEventBridgeRestoreCompleted"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.validator[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.restore_completed[0].arn
}

# RestoreValidationSucceeded is emitted as 1 or 0 per validation (EMF, one
# ResourceType dimension). A minimum below 1 means a validation failed.
resource "aws_cloudwatch_metric_alarm" "restore_validation_failed" {
  provider = aws.dr
  for_each = local.validator_enabled ? local.validator_types : toset([])

  alarm_name          = "${var.name_prefix}-restore-validation-failed-${lower(each.value)}"
  alarm_description   = "A restore test of a ${each.value} recovery point in the DR vault failed validation. Runbook: docs/operations.md."
  namespace           = "BackupDR/RestoreTesting"
  metric_name         = "RestoreValidationSucceeded"
  dimensions          = { ResourceType = each.value }
  statistic           = "Minimum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [module.dr_vault.notification_topic_arn]
  tags                = var.tags
}
