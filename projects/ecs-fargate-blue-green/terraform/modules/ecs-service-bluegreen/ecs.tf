resource "aws_cloudwatch_log_group" "service" {
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

# Created without a version: the value is set out of band
# (aws secretsmanager put-secret-value), so it never enters Terraform state.
resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.name_prefix}/${var.environment}/db"
  description             = "${local.name} database credentials (JSON with a password key)"
  recovery_window_in_days = var.secret_recovery_window_days
  tags                    = local.tags
}

# The bootstrap revision only. Every CodeDeploy deployment registers its own
# revision from deploy/taskdef.template.json (scripts/render_appspec.py), so
# keep the two in step: same container name, port, secrets and log options.
resource "aws_ecs_task_definition" "app" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  tags                     = local.tags

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name                   = var.container_name
      image                  = var.bootstrap_image
      essential              = true
      user                   = "10001:10001"
      readonlyRootFilesystem = true
      portMappings           = [{ containerPort = var.container_port, protocol = "tcp" }]
      environment = [
        { name = "APP_ENV", value = var.environment },
        { name = "PORT", value = tostring(var.container_port) },
        { name = "IMAGE_TAG", value = local.bootstrap_tag },
      ]
      secrets = [
        { name = "DB_PASSWORD", valueFrom = "${aws_secretsmanager_secret.app.arn}:password::" }
      ]
      healthCheck = {
        command     = ["CMD", "python", "/app/healthcheck.py"]
        interval    = 15
        timeout     = 3
        retries     = 3
        startPeriod = 10
      }
      linuxParameters = { initProcessEnabled = true }
      stopTimeout     = 20
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.service.name
          awslogs-region        = local.region
          awslogs-stream-prefix = var.environment
          mode                  = "non-blocking"
          max-buffer-size       = "4m"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "app" {
  name                              = local.name
  cluster                           = var.cluster_name
  task_definition                   = aws_ecs_task_definition.app.arn
  desired_count                     = var.desired_count
  platform_version                  = var.platform_version
  health_check_grace_period_seconds = 30
  enable_ecs_managed_tags           = true
  propagate_tags                    = "SERVICE"
  tags                              = local.tags

  # CodeDeploy, not ECS, replaces task sets and shifts traffic. No circuit
  # breaker here: it only exists for the ECS deployment controller.
  deployment_controller {
    type = "CODE_DEPLOY"
  }

  # On-demand base first, then the weights. The replacement (green) task set
  # inherits this strategy, so with spot_weight > 0 both task sets can be on
  # Fargate Spot during a deployment; the on-demand base is what guarantees
  # a floor that a Spot reclaim can't take away.
  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    base              = var.on_demand_base
    weight            = var.on_demand_weight
  }

  dynamic "capacity_provider_strategy" {
    for_each = var.spot_weight > 0 ? [1] : []
    content {
      capacity_provider = "FARGATE_SPOT"
      base              = 0
      weight            = var.spot_weight
    }
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this["blue"].arn
    container_name   = var.container_name
    container_port   = var.container_port
  }

  # After creation CodeDeploy owns these:
  #  - task_definition: each deployment points the service at a new revision
  #    through a new task set; Terraform must not "revert" it to the
  #    bootstrap revision.
  #  - load_balancer: after a deployment the live target group may be green;
  #    the attribute Terraform sees would drift every other release.
  #  - desired_count: Application Auto Scaling owns it.
  # Changing the task definition here therefore does NOT deploy anything;
  # deployments go through aws deploy create-deployment (docs/operations.md).
  lifecycle {
    ignore_changes = [task_definition, load_balancer, desired_count]
  }

  depends_on = [aws_lb_listener.production, aws_lb_listener.test, aws_iam_role_policy.execution]
}
