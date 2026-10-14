# One role per function. Each policy lists only the actions that function's
# code (or its event source mapping) calls, scoped to this stack's resources.
# No managed policies: AWSLambdaBasicExecutionRole would add
# logs:CreateLogGroup on "*", which isn't needed because Terraform owns the
# log groups.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

# ---- ingest ---------------------------------------------------------------

resource "aws_iam_role" "ingest" {
  name               = "${local.ingest_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "ingest" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.ingest.arn}:*"]
  }

  statement {
    sid       = "EnqueueOrders"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.orders.arn]
  }
}

resource "aws_iam_role_policy" "ingest" {
  name   = "least-privilege"
  role   = aws_iam_role.ingest.id
  policy = data.aws_iam_policy_document.ingest.json
}

# ---- process --------------------------------------------------------------

resource "aws_iam_role" "process" {
  name               = "${local.process_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "process" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.process.arn}:*"]
  }

  # Used by the event source mapping on the function's behalf.
  statement {
    sid       = "ConsumeOrdersQueue"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.orders.arn]
  }

  # PutItem: idempotency claim (conditional) and order record.
  # UpdateItem: mark the claim completed. DeleteItem: release after failure.
  # No GetItem/Query/Scan: duplicates read the blocking item from the failed
  # conditional write (ReturnValuesOnConditionCheckFailure).
  statement {
    sid       = "IdempotencyAndOrderState"
    actions   = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.orders.arn]
  }

  statement {
    sid       = "PublishDomainEvents"
    actions   = ["events:PutEvents"]
    resources = [aws_cloudwatch_event_bus.orders.arn]
  }
}

resource "aws_iam_role_policy" "process" {
  name   = "least-privilege"
  role   = aws_iam_role.process.id
  policy = data.aws_iam_policy_document.process.json
}
