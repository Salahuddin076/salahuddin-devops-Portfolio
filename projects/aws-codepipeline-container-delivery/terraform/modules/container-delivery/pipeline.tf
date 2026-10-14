# The connection is created PENDING. Someone with access to the GitHub
# organisation must complete the handshake once in the console (Developer
# Tools > Settings > Connections > Update pending connection). Until then the
# Source action fails. See docs/operations.md, "Bootstrap".
resource "aws_codeconnections_connection" "github" {
  name          = substr("${var.name_prefix}-github", 0, 32)
  provider_type = "GitHub"
  tags          = local.tags
}

resource "aws_sns_topic" "approval" {
  name              = "${var.name_prefix}-prod-approval"
  kms_master_key_id = aws_kms_key.this.arn
  tags              = local.tags
}

resource "aws_sns_topic_subscription" "approval_email" {
  for_each = toset(var.approval_emails)

  topic_arn = aws_sns_topic.approval.arn
  protocol  = "email"
  endpoint  = each.key
}

resource "aws_codepipeline" "this" {
  name          = "${var.name_prefix}-delivery"
  role_arn      = aws_iam_role.pipeline.arn
  pipeline_type = "V2"
  # QUEUED: executions run in order and never overtake one another, so a
  # newer commit cannot jump ahead of an older one waiting for approval.
  execution_mode = "QUEUED"
  tags           = local.tags

  artifact_store {
    type     = "S3"
    location = aws_s3_bucket.artifacts.bucket

    encryption_key {
      id   = aws_kms_key.this.arn
      type = "KMS"
    }
  }

  trigger {
    provider_type = "CodeStarSourceConnection"

    git_configuration {
      source_action_name = "Source"

      push {
        branches {
          includes = [var.branch]
        }

        dynamic "file_paths" {
          for_each = length(var.trigger_file_paths) > 0 ? [1] : []
          content {
            includes = var.trigger_file_paths
          }
        }
      }
    }
  }

  stage {
    name = "Source"

    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      namespace        = "SourceVariables"
      output_artifacts = ["source"]

      configuration = {
        ConnectionArn        = aws_codeconnections_connection.github.arn
        FullRepositoryId     = var.repository_full_id
        BranchName           = var.branch
        OutputArtifactFormat = "CODE_ZIP"
        DetectChanges        = "false" # the V2 trigger above starts executions
      }
    }
  }

  stage {
    name = "Test"

    action {
      name            = "UnitTestsAndLint"
      category        = "Test"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["source"]

      configuration = {
        ProjectName = aws_codebuild_project.this["test"].name
      }
    }
  }

  stage {
    name = "Build"

    action {
      name             = "BuildScanPush"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["source"]
      output_artifacts = ["imagedefinitions"]

      configuration = {
        ProjectName = aws_codebuild_project.this["build"].name
      }
    }
  }

  stage {
    name = "DeployStaging"

    action {
      name            = "DeployToEcsStaging"
      category        = "Deploy"
      owner           = "AWS"
      provider        = "ECS"
      version         = "1"
      input_artifacts = ["imagedefinitions"]

      configuration = {
        ClusterName       = aws_ecs_cluster.this.name
        ServiceName       = aws_ecs_service.app["staging"].name
        FileName          = "imagedefinitions.json"
        DeploymentTimeout = "20"
      }
    }

    # If the deploy fails after ECS has already rolled itself back, roll the
    # stage back too, so the pipeline's view matches what is running.
    on_failure {
      result = "ROLLBACK"
    }
  }

  stage {
    name = "ApproveProd"

    action {
      name               = "ManualApproval"
      category           = "Approval"
      owner              = "AWS"
      provider           = "Manual"
      version            = "1"
      timeout_in_minutes = var.approval_timeout_minutes

      configuration = {
        NotificationArn = aws_sns_topic.approval.arn
        CustomData      = "Promote commit #{SourceVariables.CommitId} to prod. Staging is running it now; check /version and the staging logs before approving."
      }
    }
  }

  stage {
    name = "DeployProd"

    action {
      name            = "DeployToEcsProd"
      category        = "Deploy"
      owner           = "AWS"
      provider        = "ECS"
      version         = "1"
      input_artifacts = ["imagedefinitions"]

      configuration = {
        ClusterName       = aws_ecs_cluster.this.name
        ServiceName       = aws_ecs_service.app["prod"].name
        FileName          = "imagedefinitions.json"
        DeploymentTimeout = "30"
      }
    }

    on_failure {
      result = "ROLLBACK"
    }
  }
}
