data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region
  partition  = data.aws_partition.current.partition

  tags = merge(var.tags, { component = "container-delivery" })

  # Deploy order: staging first, then prod behind the manual approval.
  environment_names = ["staging", "prod"]

  log_group_arn_prefix = "arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group"
}

# ----------------------------------------------------------------------------- KMS
# One customer managed key for the artifact bucket, ECR, the secrets, the log
# groups and the approval topic. Principals get kms:* actions through IAM
# (the root statement delegates to IAM); CloudWatch Logs gets a scoped grant
# in the key policy because it is a service principal.

data "aws_iam_policy_document" "kms" {
  statement {
    sid       = "AccountAdministersKeyThroughIam"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }

  statement {
    sid = "CloudWatchLogsForThisStackOnly"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:Describe*",
    ]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["logs.${local.region}.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values = [
        "${local.log_group_arn_prefix}:/ecs/${var.name_prefix}-*",
        "${local.log_group_arn_prefix}:/aws/codebuild/${var.name_prefix}-*",
      ]
    }
  }
}

resource "aws_kms_key" "this" {
  description             = "${var.name_prefix} container delivery: artifacts, ECR, secrets, logs, approval topic"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.kms.json
  tags                    = local.tags
}

resource "aws_kms_alias" "this" {
  name          = "alias/${var.name_prefix}-delivery"
  target_key_id = aws_kms_key.this.key_id
}

# ----------------------------------------------------------------------------- secrets
# Containers only: no aws_secretsmanager_secret_version on purpose. Values are
# set out of band (console, CLI or a separate secrets pipeline), so they never
# appear in Terraform state or plan output. See docs/operations.md.

# One DB secret per environment, so the staging execution role cannot read
# prod credentials.
resource "aws_secretsmanager_secret" "db" {
  for_each = toset(local.environment_names)

  name                    = "${var.name_prefix}/${each.key}/db"
  description             = "Database credentials for the ${each.key} app, JSON {\"username\": ..., \"password\": ...}. Value set out of band."
  kms_key_id              = aws_kms_key.this.arn
  recovery_window_in_days = 7
  tags                    = merge(local.tags, { environment = each.key })
}

resource "aws_secretsmanager_secret" "registry" {
  name                    = var.registry_secret_name
  description             = "Docker Hub pull credentials for CodeBuild, JSON {\"username\": ..., \"password\": ...}. Value set out of band."
  kms_key_id              = aws_kms_key.this.arn
  recovery_window_in_days = 7
  tags                    = local.tags
}

# ----------------------------------------------------------------------------- logs

resource "aws_cloudwatch_log_group" "ecs" {
  for_each = toset(local.environment_names)

  name              = "/ecs/${var.name_prefix}-${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.this.arn
  tags              = merge(local.tags, { environment = each.key })
}

resource "aws_cloudwatch_log_group" "codebuild" {
  for_each = toset(["test", "build"])

  name              = "/aws/codebuild/${var.name_prefix}-${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.this.arn
  tags              = local.tags
}
