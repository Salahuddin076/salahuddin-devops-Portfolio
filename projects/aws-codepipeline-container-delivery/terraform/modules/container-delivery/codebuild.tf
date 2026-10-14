locals {
  codebuild_projects = {
    test = {
      description = "Unit tests and buildspec policy lint (JUnit report)"
      buildspec   = "buildspec-test.yml"
      privileged  = false
      env = {
        PROJECT_DIR = var.project_dir
      }
    }
    build = {
      description = "Docker build, Trivy gate, ECR push, imagedefinitions.json"
      buildspec   = "buildspec-build.yml"
      privileged  = true # docker build needs the Docker daemon
      env = {
        PROJECT_DIR        = var.project_dir
        ECR_REPOSITORY_URI = aws_ecr_repository.app.repository_url
        CONTAINER_NAME     = var.container_name
      }
    }
  }

  buildspec_prefix = var.project_dir == "." ? "buildspec" : "${var.project_dir}/buildspec"
}

resource "aws_codebuild_project" "this" {
  for_each = local.codebuild_projects

  name           = "${var.name_prefix}-${each.key}"
  description    = each.value.description
  service_role   = aws_iam_role.codebuild[each.key].arn
  build_timeout  = var.build_timeout_minutes
  queued_timeout = 60
  encryption_key = aws_kms_key.this.arn
  tags           = local.tags

  source {
    type      = "CODEPIPELINE"
    buildspec = "${local.buildspec_prefix}/${each.value.buildspec}"
  }

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    type                        = "LINUX_CONTAINER"
    compute_type                = var.codebuild_compute_type
    image                       = var.codebuild_image
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = each.value.privileged

    dynamic "environment_variable" {
      for_each = each.value.env
      content {
        name  = environment_variable.key
        value = environment_variable.value
        type  = "PLAINTEXT"
      }
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.codebuild[each.key].name
      status     = "ENABLED"
    }
  }

  dynamic "vpc_config" {
    for_each = var.codebuild_in_vpc ? [1] : []
    content {
      vpc_id             = var.vpc_id
      subnets            = var.subnet_ids
      security_group_ids = [aws_security_group.codebuild[0].id]
    }
  }
}
