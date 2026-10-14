# One role per stage and per environment, each with only what its step does.
# Every trust policy pins aws:SourceAccount (confused-deputy protection).
# No AWS managed policies are attached.

# ----------------------------------------------------------------------------- CodeBuild

data "aws_iam_policy_document" "codebuild_trust" {
  for_each = local.codebuild_projects

  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:codebuild:${local.region}:${local.account_id}:project/${var.name_prefix}-${each.key}"]
    }
  }
}

resource "aws_iam_role" "codebuild" {
  for_each = local.codebuild_projects

  name               = "${var.name_prefix}-codebuild-${each.key}"
  description        = "CodeBuild ${each.key} stage for ${var.name_prefix}"
  assume_role_policy = data.aws_iam_policy_document.codebuild_trust[each.key].json
  tags               = local.tags
}

data "aws_iam_policy_document" "codebuild" {
  for_each = local.codebuild_projects

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.codebuild[each.key].arn}:*"]
  }

  statement {
    sid = "ReadPipelineArtifacts"
    # Only the build stage writes an output artifact (imagedefinitions.json).
    actions   = each.key == "build" ? ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"] : ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.artifacts.arn}/*"]
  }

  statement {
    sid       = "UseStackKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [aws_kms_key.this.arn]
  }

  statement {
    sid = "PublishReports"
    actions = [
      "codebuild:CreateReportGroup",
      "codebuild:CreateReport",
      "codebuild:UpdateReport",
      "codebuild:BatchPutTestCases",
    ]
    resources = ["arn:${local.partition}:codebuild:${local.region}:${local.account_id}:report-group/${var.name_prefix}-${each.key}-*"]
  }

  dynamic "statement" {
    for_each = each.key == "build" ? [1] : []
    content {
      sid       = "EcrLogin"
      actions   = ["ecr:GetAuthorizationToken"] # does not support resource-level permissions
      resources = ["*"]
    }
  }

  dynamic "statement" {
    for_each = each.key == "build" ? [1] : []
    content {
      sid = "PushToThisRepositoryOnly"
      actions = [
        "ecr:BatchCheckLayerAvailability",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
      ]
      resources = [aws_ecr_repository.app.arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "build" ? [1] : []
    content {
      sid       = "ReadRegistryCredentialsOnly"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [aws_secretsmanager_secret.registry.arn]
    }
  }

  dynamic "statement" {
    for_each = var.codebuild_in_vpc ? [1] : []
    content {
      sid = "VpcNetworkInterfaces"
      actions = [
        "ec2:CreateNetworkInterface",
        "ec2:DeleteNetworkInterface",
        "ec2:DescribeDhcpOptions",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeSubnets",
        "ec2:DescribeVpcs",
      ]
      resources = ["*"] # Describe* and CreateNetworkInterface are not resource-scoped here
    }
  }

  dynamic "statement" {
    for_each = var.codebuild_in_vpc ? [1] : []
    content {
      sid       = "VpcAttachInConfiguredSubnetsOnly"
      actions   = ["ec2:CreateNetworkInterfacePermission"]
      resources = ["arn:${local.partition}:ec2:${local.region}:${local.account_id}:network-interface/*"]

      condition {
        test     = "StringEquals"
        variable = "ec2:AuthorizedService"
        values   = ["codebuild.amazonaws.com"]
      }

      condition {
        test     = "ArnEquals"
        variable = "ec2:Subnet"
        values   = [for s in var.subnet_ids : "arn:${local.partition}:ec2:${local.region}:${local.account_id}:subnet/${s}"]
      }
    }
  }
}

resource "aws_iam_role_policy" "codebuild" {
  for_each = local.codebuild_projects

  name   = "${var.name_prefix}-codebuild-${each.key}"
  role   = aws_iam_role.codebuild[each.key].id
  policy = data.aws_iam_policy_document.codebuild[each.key].json
}

# ----------------------------------------------------------------------------- ECS tasks

data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:ecs:${local.region}:${local.account_id}:*"]
    }
  }
}

# Execution role: used by the ECS agent to pull the image, write logs and
# resolve `secrets` before the container starts. Never visible to app code.
resource "aws_iam_role" "execution" {
  for_each = toset(local.environment_names)

  name               = "${var.name_prefix}-${each.key}-execution"
  description        = "ECS execution role (${each.key}): image pull, logs, ${each.key} DB secret"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
  tags               = merge(local.tags, { environment = each.key })
}

data "aws_iam_policy_document" "execution" {
  for_each = toset(local.environment_names)

  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid       = "PullFromThisRepositoryOnly"
    actions   = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [aws_ecr_repository.app.arn]
  }

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.ecs[each.key].arn}:*"]
  }

  statement {
    sid       = "ReadOwnEnvironmentSecretOnly"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.db[each.key].arn]
  }

  statement {
    sid       = "DecryptSecretThroughSecretsManager"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.this.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${local.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "execution" {
  for_each = toset(local.environment_names)

  name   = "${var.name_prefix}-${each.key}-execution"
  role   = aws_iam_role.execution[each.key].id
  policy = data.aws_iam_policy_document.execution[each.key].json
}

# Task role: the identity the app code runs as. The demo app calls no AWS
# APIs, so it has no permissions at all. Add statements here, per
# environment, when the app needs them.
resource "aws_iam_role" "task" {
  for_each = toset(local.environment_names)

  name               = "${var.name_prefix}-${each.key}-task"
  description        = "ECS task role (${each.key}): intentionally empty"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
  tags               = merge(local.tags, { environment = each.key })
}

# ----------------------------------------------------------------------------- CodePipeline

data "aws_iam_policy_document" "pipeline_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codepipeline.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name               = "${var.name_prefix}-pipeline"
  description        = "CodePipeline service role for ${var.name_prefix}"
  assume_role_policy = data.aws_iam_policy_document.pipeline_trust.json
  tags               = local.tags
}

data "aws_iam_policy_document" "pipeline" {
  statement {
    sid       = "ArtifactObjects"
    actions   = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"]
    resources = ["${aws_s3_bucket.artifacts.arn}/*"]
  }

  statement {
    sid       = "ArtifactBucket"
    actions   = ["s3:GetBucketVersioning", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid       = "UseStackKey"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [aws_kms_key.this.arn]
  }

  statement {
    sid       = "UseSourceConnection"
    actions   = ["codeconnections:UseConnection", "codestar-connections:UseConnection"]
    resources = [aws_codeconnections_connection.github.arn]
  }

  statement {
    sid       = "RunBuilds"
    actions   = ["codebuild:StartBuild", "codebuild:BatchGetBuilds"]
    resources = [for p in aws_codebuild_project.this : p.arn]
  }

  statement {
    sid       = "UpdateTheTwoServices"
    actions   = ["ecs:DescribeServices", "ecs:UpdateService"]
    resources = [for s in aws_ecs_service.app : s.id]
  }

  statement {
    sid = "TaskDefinitionsAndTasks"
    # RegisterTaskDefinition and DescribeTaskDefinition do not support
    # resource-level permissions.
    actions   = ["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"]
    resources = ["*"]
  }

  statement {
    sid       = "WatchDeploymentTasks"
    actions   = ["ecs:DescribeTasks", "ecs:ListTasks"]
    resources = ["*"]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.this.arn]
    }
  }

  statement {
    sid       = "TagNewTaskDefinitions"
    actions   = ["ecs:TagResource"]
    resources = ["arn:${local.partition}:ecs:${local.region}:${local.account_id}:task-definition/${var.name_prefix}-*"]

    condition {
      test     = "StringEquals"
      variable = "ecs:CreateAction"
      values   = ["RegisterTaskDefinition"]
    }
  }

  statement {
    sid       = "PassOnlyTheseTaskRolesToEcs"
    actions   = ["iam:PassRole"]
    resources = concat([for r in aws_iam_role.execution : r.arn], [for r in aws_iam_role.task : r.arn])

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid       = "NotifyApprovers"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.approval.arn]
  }
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "${var.name_prefix}-pipeline"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline.json
}
