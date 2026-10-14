# ---- ECS task execution role: pull one repository, read one secret, write one log group

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
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
  tags               = local.tags
}

data "aws_iam_policy_document" "execution" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # GetAuthorizationToken has no resource-level permissions
  }
  statement {
    sid       = "EcrPullOneRepository"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
    resources = [var.ecr_repository_arn]
  }
  statement {
    sid       = "ReadAppSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
  statement {
    sid       = "WriteServiceLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.service.arn}:*"]
  }
}

resource "aws_iam_role_policy" "execution" {
  name   = "execution"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution.json
}

# ---- Task role: the application needs no AWS API access, so it has no policy.

resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
  tags               = local.tags
}

# ---- CodeDeploy service role

data "aws_iam_policy_document" "codedeploy_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codedeploy.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "codedeploy" {
  name               = "${local.name}-codedeploy"
  assume_role_policy = data.aws_iam_policy_document.codedeploy_trust.json
  tags               = local.tags
}

# The AWS managed policy for CodeDeploy on ECS. It is broader than this one
# service (any ECS service, any listener or rule, CodeDeployHook_* Lambdas),
# which is the documented trade-off: a hand-scoped replacement can't be
# verified without deploying. See docs/security.md.
resource "aws_iam_role_policy_attachment" "codedeploy" {
  role       = aws_iam_role.codedeploy.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AWSCodeDeployRoleForECS"
}

# ---- Hook Lambda role: report hook status, read this deployment group's revisions

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "hooks" {
  name               = "${local.name}-hooks"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.tags
}

data "aws_iam_policy_document" "hooks" {
  statement {
    sid       = "ReportHookStatus"
    actions   = ["codedeploy:PutLifecycleEventHookExecutionStatus", "codedeploy:GetDeployment"]
    resources = ["arn:${local.partition}:codedeploy:${local.region}:${local.account_id}:deploymentgroup:${aws_codedeploy_app.this.name}/${local.name}"]
  }
  statement {
    sid       = "ReadDeployedTaskDefinition"
    actions   = ["ecs:DescribeTaskDefinition"]
    resources = ["*"] # DescribeTaskDefinition has no resource-level permissions
  }
  statement {
    sid       = "WriteHookLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [for g in aws_cloudwatch_log_group.hooks : "${g.arn}:*"]
  }
  statement {
    sid = "VpcNetworkInterfaces"
    actions = [
      "ec2:CreateNetworkInterface",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DeleteNetworkInterface",
      "ec2:AssignPrivateIpAddresses",
      "ec2:UnassignPrivateIpAddresses",
    ]
    resources = ["*"] # required by Lambda VPC networking
  }
}

resource "aws_iam_role_policy" "hooks" {
  name   = "hooks"
  role   = aws_iam_role.hooks.id
  policy = data.aws_iam_policy_document.hooks.json
}
