# Shared platform for all environments: one ECR repository (one image,
# promoted dev -> staging -> prod by tag) and one ECS cluster with FARGATE
# and FARGATE_SPOT capacity providers. Load balancing is per environment:
# each ecs-service-bluegreen module owns its ALB, because CodeDeploy shifts
# traffic by rewriting listener default actions (docs/decisions/0004).

locals {
  tags = merge(var.tags, { component = "shared-platform" })
}

# ---- ECR -----------------------------------------------------------------

resource "aws_ecr_repository" "app" {
  name                 = var.ecr_repository_name
  image_tag_mutability = "IMMUTABLE"
  tags                 = local.tags

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the newest ${var.ecr_keep_images} images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.ecr_keep_images
      }
      action = { type = "expire" }
    }]
  })
}

# ---- ECS cluster -----------------------------------------------------------

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
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  # Services always pass their own strategy; this default only applies to
  # ad-hoc RunTask calls.
  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}
