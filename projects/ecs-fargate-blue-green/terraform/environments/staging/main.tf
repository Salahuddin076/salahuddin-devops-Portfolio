# staging: the settings come from config/environments/staging.json, the same
# file scripts/check_bluegreen_policy.py lints (single source of truth).
# Everything else in this file is identical across dev, staging and prod.

locals {
  environment = "staging"
  settings    = jsondecode(file("${path.module}/../../../config/environments/${local.environment}.json"))
}

check "settings_match_this_root" {
  assert {
    condition     = local.settings.environment == local.environment
    error_message = "config/environments/${local.environment}.json declares a different environment."
  }
}

# The shared ECR repository, looked up by the name the shared root gives it.
data "aws_ecr_repository" "app" {
  name = var.ecr_repository_name
}

module "service" {
  source = "../../modules/ecs-service-bluegreen"

  name_prefix = var.name_prefix
  environment = local.environment

  vpc_id             = var.vpc_id
  public_subnet_ids  = var.public_subnet_ids
  private_subnet_ids = var.private_subnet_ids
  cluster_name       = "${var.name_prefix}-cluster"
  certificate_arn    = var.certificate_arn
  ecr_repository_arn = data.aws_ecr_repository.app.arn

  host_header                  = local.settings.host_header
  test_listener_port           = local.settings.test_listener_port
  test_listener_cidrs          = local.settings.test_listener_cidrs
  deregistration_delay_seconds = local.settings.deregistration_delay_seconds

  bootstrap_image    = var.bootstrap_image
  cpu                = local.settings.task.cpu
  memory             = local.settings.task.memory
  cpu_architecture   = local.settings.task.cpu_architecture
  log_retention_days = local.settings.task.log_retention_days

  on_demand_base   = local.settings.capacity.on_demand_base
  on_demand_weight = local.settings.capacity.on_demand_weight
  spot_weight      = local.settings.capacity.spot_weight

  desired_count       = local.settings.scaling.desired_count
  min_capacity        = local.settings.scaling.min_capacity
  max_capacity        = local.settings.scaling.max_capacity
  cpu_target_percent  = local.settings.scaling.cpu_target_percent
  requests_per_target = local.settings.scaling.requests_per_target

  deployment_config_name        = local.settings.deployment_config_name
  manual_reroute                = local.settings.manual_reroute
  reroute_wait_minutes          = local.settings.reroute_wait_minutes
  termination_wait_minutes      = local.settings.termination_wait_minutes
  auto_rollback_events          = local.settings.auto_rollback.events
  alarms_enabled                = local.settings.alarms.enabled
  target_5xx_threshold          = local.settings.alarms.target_5xx_threshold
  p95_latency_threshold_seconds = local.settings.alarms.p95_latency_threshold_seconds
  alarm_evaluation_periods      = local.settings.alarms.evaluation_periods

  hooks_zip_path                = var.hooks_zip_path
  smoke_requests                = local.settings.smoke.requests
  smoke_p95_budget_ms           = local.settings.smoke.p95_budget_ms
  smoke_request_timeout_seconds = local.settings.smoke.request_timeout_seconds
}
