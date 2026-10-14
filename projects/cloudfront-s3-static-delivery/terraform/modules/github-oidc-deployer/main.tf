# GitHub Actions -> AWS without stored keys.
#
# A workflow job with `permissions: id-token: write` asks GitHub for a signed
# OIDC token, and aws-actions/configure-aws-credentials exchanges it with
# sts:AssumeRoleWithWebIdentity. The trust policy below decides which tokens
# are accepted: audience sts.amazonaws.com, and a subject naming this exact
# repository plus an allowed branch or GitHub environment. Exact matches
# only (StringEquals): no "repo:org/*" wildcards, which would let every
# repository in the organisation, and every branch, deploy this site.

locals {
  oidc_host = "token.actions.githubusercontent.com"

  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.existing_oidc_provider_arn

  allowed_subjects = concat(
    [for b in var.allowed_branches : "repo:${var.github_repository}:ref:refs/heads/${b}"],
    [for e in var.github_environments : "repo:${var.github_repository}:environment:${e}"],
  )

  tags = merge(var.tags, { module = "github-oidc-deployer" })
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url            = "https://${local.oidc_host}"
  client_id_list = ["sts.amazonaws.com"]
  # No thumbprint_list: IAM validates GitHub's certificate against its own
  # trusted root CAs for this provider, so a pinned thumbprint only adds a
  # way to break when GitHub rotates certificates.
  tags = local.tags
}

data "aws_iam_policy_document" "trust" {
  statement {
    sid     = "GitHubActionsOIDC"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = local.allowed_subjects
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = var.role_name
  description          = "GitHub Actions deploy role for ${var.github_repository}: sync one bucket, invalidate one distribution"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = var.max_session_duration
  permissions_boundary = var.permissions_boundary_arn
  tags                 = local.tags

  lifecycle {
    precondition {
      condition     = length(local.allowed_subjects) > 0
      error_message = "At least one of allowed_branches or github_environments must be non-empty, or no workflow could assume the role."
    }
  }
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "ListSiteBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [var.bucket_arn]
  }

  statement {
    sid       = "WriteSiteObjects"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${var.bucket_arn}/*"]
  }

  statement {
    sid       = "InvalidateSiteDistribution"
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [var.distribution_arn]
  }

  dynamic "statement" {
    for_each = var.kms_key_arn == null ? [] : [var.kms_key_arn]
    content {
      sid       = "UseSiteBucketKey"
      effect    = "Allow"
      actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
      resources = [statement.value]
    }
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "static-site-deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
