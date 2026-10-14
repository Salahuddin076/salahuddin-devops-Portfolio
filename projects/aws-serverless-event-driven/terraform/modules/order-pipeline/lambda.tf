# One zip for both functions: the handlers share validation, logging and the
# adapters, and Lambda picks the module through `handler`. boto3 is provided
# by the runtime, so the package has no third-party dependencies.
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = local.source_dir
  output_path = "${path.root}/.build/${var.name_prefix}-lambda.zip"
  excludes    = ["__pycache__"]
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${local.ingest_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "process" {
  name              = "/aws/lambda/${local.process_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_function" "ingest" {
  function_name    = local.ingest_name
  description      = "POST /orders: validate, require Idempotency-Key, enqueue to SQS."
  role             = aws_iam_role.ingest.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "ingest.handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  memory_size      = var.lambda_memory_mb
  # Well under the HTTP API's 30 s integration limit; the function only does
  # one SQS SendMessage.
  timeout = 10

  environment {
    variables = {
      QUEUE_URL = aws_sqs_queue.orders.url
      LOG_LEVEL = var.log_level
    }
  }

  logging_config {
    log_format = "Text" # the handlers already write one JSON object per line
    log_group  = aws_cloudwatch_log_group.ingest.name
  }

  tags = var.tags

  depends_on = [aws_iam_role_policy.ingest]
}

resource "aws_lambda_function" "process" {
  function_name    = local.process_name
  description      = "SQS consumer: idempotent order acceptance, publishes OrderAccepted."
  role             = aws_iam_role.process.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "process.handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  memory_size      = var.lambda_memory_mb
  timeout          = var.processor_timeout_seconds

  # Caps pressure on DynamoDB/EventBridge and guarantees the processor
  # capacity even if other functions in the account spike.
  reserved_concurrent_executions = var.processor_reserved_concurrency

  environment {
    variables = {
      TABLE_NAME              = aws_dynamodb_table.orders.name
      EVENT_BUS_NAME          = aws_cloudwatch_event_bus.orders.name
      IDEMPOTENCY_TTL_SECONDS = tostring(var.idempotency_ttl_hours * 3600)
      # A crashed invocation's lock frees up once the function could no
      # longer be running.
      IDEMPOTENCY_LOCK_SECONDS = tostring(var.processor_timeout_seconds + 5)
      LOG_LEVEL                = var.log_level
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.process.name
  }

  tags = var.tags

  depends_on = [aws_iam_role_policy.process]
}

resource "aws_lambda_event_source_mapping" "process" {
  event_source_arn                   = aws_sqs_queue.orders.arn
  function_name                      = aws_lambda_function.process.arn
  batch_size                         = var.batch_size
  maximum_batching_window_in_seconds = var.batching_window_seconds

  # Only the failed messageIds are retried; successes in the batch are deleted.
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.processor_max_concurrency
  }

  lifecycle {
    precondition {
      condition     = var.processor_max_concurrency <= var.processor_reserved_concurrency
      error_message = "processor_max_concurrency must not exceed processor_reserved_concurrency, or the event source mapping will be throttled."
    }
  }
}
