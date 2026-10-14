module "order_pipeline" {
  source = "../../modules/order-pipeline"

  name_prefix = "orders-${var.environment}"

  processor_reserved_concurrency = 10
  processor_max_concurrency      = 10
  max_receive_count              = 5
  idempotency_ttl_hours          = 24
  api_throttle_rate_limit        = 50
  api_throttle_burst_limit       = 100
  log_retention_days             = var.environment == "prod" ? 90 : 14

  # Throwaway dev stacks can be destroyed without a manual step.
  table_deletion_protection = var.environment == "prod"

  alarm_emails        = var.alarm_emails
  notification_emails = var.notification_emails

  tags = {
    cost-center = "orders-platform"
  }
}
