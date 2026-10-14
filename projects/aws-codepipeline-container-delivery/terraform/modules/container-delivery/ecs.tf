resource "aws_ecs_cluster" "this" {
  name = "${var.name_prefix}-cluster"
  tags = local.tags

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# The initial revision points at a `bootstrap` tag that the pipeline never
# produces. The first pipeline run registers a new revision with the commit
# SHA image (imagedefinitions.json), and Terraform ignores the service's
# task_definition from then on. See docs/operations.md, "Bootstrap".
resource "aws_ecs_task_definition" "app" {
  for_each = toset(local.environment_names)

  family                   = "${var.name_prefix}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.environments[each.key].cpu
  memory                   = var.environments[each.key].memory
  execution_role_arn       = aws_iam_role.execution[each.key].arn
  task_role_arn            = aws_iam_role.task[each.key].arn
  tags                     = merge(local.tags, { environment = each.key })

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64" # matches the x86_64 CodeBuild image that builds it
  }

  container_definitions = jsonencode([
    {
      name                   = var.container_name
      image                  = "${aws_ecr_repository.app.repository_url}:bootstrap"
      essential              = true
      user                   = "10001:10001"
      readonlyRootFilesystem = true
      portMappings = [
        { containerPort = var.container_port, protocol = "tcp" }
      ]
      environment = [
        { name = "APP_ENV", value = each.key },
        { name = "PORT", value = tostring(var.container_port) },
        { name = "REQUIRE_DB_PASSWORD", value = "true" },
      ]
      # ECS resolves this before the container starts. The suffix selects
      # one JSON key: <secret-arn>:<json-key>:<version-stage>:<version-id>.
      # Without ":password::" the variable would hold the whole JSON document.
      secrets = [
        { name = "DB_PASSWORD", valueFrom = "${aws_secretsmanager_secret.db[each.key].arn}:password::" }
      ]
      # ECS ignores the image HEALTHCHECK, so the probe is repeated here.
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
          awslogs-group         = aws_cloudwatch_log_group.ecs[each.key].name
          awslogs-region        = local.region
          awslogs-stream-prefix = each.key
          mode                  = "non-blocking"
          max-buffer-size       = "4m"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "app" {
  for_each = toset(local.environment_names)

  name                   = "${var.name_prefix}-${each.key}"
  cluster                = aws_ecs_cluster.this.id
  task_definition        = aws_ecs_task_definition.app[each.key].arn
  desired_count          = var.environments[each.key].desired_count
  launch_type            = "FARGATE"
  platform_version       = "LATEST"
  propagate_tags         = "SERVICE"
  enable_execute_command = false
  wait_for_steady_state  = false
  tags                   = merge(local.tags, { environment = each.key })

  # Rolling update: start new tasks before stopping old ones.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_controller {
    type = "ECS"
  }

  # Tasks that fail to start or fail their health check trip the breaker;
  # ECS then rolls the service back to the last completed deployment.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = var.assign_public_ip
  }

  lifecycle {
    # The pipeline owns the running revision after the first release.
    ignore_changes = [task_definition]
  }

  depends_on = [aws_iam_role_policy.execution]
}
