resource "aws_cloudwatch_log_group" "hooks" {
  for_each = local.hooks

  name              = "/aws/lambda/${each.value.function_name}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

# The hooks run in the VPC's private subnets. Their requests to the
# internet-facing ALB leave through the NAT gateway, so the NAT EIPs (/32)
# must be in test_listener_cidrs or BeforeAllowTraffic can't reach the test
# listener (docs/operations.md, "Hook can't reach the test listener").
resource "aws_lambda_function" "hooks" {
  for_each = local.hooks

  function_name    = each.value.function_name
  description      = "${local.name} CodeDeploy ${each.key == "before" ? "BeforeAllowTraffic" : "AfterAllowTraffic"} smoke tests"
  role             = aws_iam_role.hooks.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = each.value.handler
  filename         = var.hooks_zip_path
  source_code_hash = filebase64sha256(var.hooks_zip_path)
  timeout          = 300
  memory_size      = 256
  tags             = local.tags

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.hooks.id]
  }

  environment {
    variables = {
      (each.value.url_variable) = each.value.url
      CONTAINER_NAME            = var.container_name
      SMOKE_REQUESTS            = tostring(var.smoke_requests)
      P95_BUDGET_MS             = tostring(var.smoke_p95_budget_ms)
      REQUEST_TIMEOUT_SECONDS   = tostring(var.smoke_request_timeout_seconds)
      HEALTH_PATH               = var.health_check_path
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.hooks[each.key].name
  }

  depends_on = [aws_iam_role_policy.hooks]
}
