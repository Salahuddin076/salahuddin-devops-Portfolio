# One environment's ECS Fargate service, deployed blue/green by CodeDeploy
# behind its own ALB. Files: alb.tf (ALB, target groups, production and test
# listeners), security.tf, iam.tf, ecs.tf, autoscaling.tf, alarms.tf,
# codedeploy.tf, hooks.tf.

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name       = "${var.name_prefix}-${var.environment}"
  region     = data.aws_region.current.region
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  tags = merge(var.tags, {
    environment = var.environment
    service     = local.name
  })

  colors = toset(["blue", "green"])

  # Same rule as scripts/render_appspec.py: the digest if present, else the tag.
  bootstrap_tag = strcontains(var.bootstrap_image, "@") ? split("@", var.bootstrap_image)[1] : reverse(split(":", var.bootstrap_image))[0]

  # Hook names start with CodeDeployHook_ because the AWS managed policy
  # AWSCodeDeployRoleForECS only allows invoking functions with that prefix.
  hooks = {
    before = {
      function_name = "CodeDeployHook_${local.name}-before-allow-traffic"
      handler       = "before_allow_traffic.handler"
      url_variable  = "TEST_BASE_URL"
      url           = "https://${var.host_header}:${var.test_listener_port}"
    }
    after = {
      function_name = "CodeDeployHook_${local.name}-after-allow-traffic"
      handler       = "after_allow_traffic.handler"
      url_variable  = "PROD_BASE_URL"
      url           = "https://${var.host_header}"
    }
  }
}

check "capacity_strategy_places_tasks" {
  assert {
    condition     = var.on_demand_weight + var.spot_weight > 0
    error_message = "At least one of on_demand_weight or spot_weight must be > 0."
  }
}

check "prod_is_not_all_at_once" {
  assert {
    condition     = var.environment != "prod" || var.deployment_config_name != "CodeDeployDefault.ECSAllAtOnce"
    error_message = "prod should use a canary or linear config (scripts/check_bluegreen_policy.py BG001)."
  }
}
