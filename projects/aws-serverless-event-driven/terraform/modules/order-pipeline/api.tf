resource "aws_apigatewayv2_api" "orders" {
  name          = "${var.name_prefix}-orders"
  description   = "Order intake API (synthetic portfolio domain)."
  protocol_type = "HTTP"
  tags          = var.tags
}

resource "aws_apigatewayv2_integration" "ingest" {
  api_id                 = aws_apigatewayv2_api.orders.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.ingest.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 12000
}

resource "aws_apigatewayv2_route" "post_orders" {
  api_id    = aws_apigatewayv2_api.orders.id
  route_key = "POST /orders"
  target    = "integrations/${aws_apigatewayv2_integration.ingest.id}"
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/vendedlogs/apigateway/${var.name_prefix}-orders"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.orders.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit    = var.api_throttle_rate_limit
    throttling_burst_limit   = var.api_throttle_burst_limit
    detailed_metrics_enabled = true
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      requestTime      = "$context.requestTime"
      sourceIp         = "$context.identity.sourceIp"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      latencyMs        = "$context.responseLatency"
      integrationError = "$context.integrationErrorMessage"
      lambdaRequestId  = "$context.integration.requestId"
    })
  }

  tags = var.tags
}

resource "aws_lambda_permission" "api_invoke_ingest" {
  statement_id  = "AllowHttpApiInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "apigateway.amazonaws.com"
  # Only this API, any stage, only the /orders route.
  source_arn = "${aws_apigatewayv2_api.orders.execution_arn}/*/*/orders"
}
