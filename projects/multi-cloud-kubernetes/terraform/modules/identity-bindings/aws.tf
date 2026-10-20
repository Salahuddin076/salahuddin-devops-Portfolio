# IRSA: one IAM role trusts the EKS cluster's OIDC provider for exactly one
# namespace/ServiceAccount subject (and exactly the sts.amazonaws.com
# audience). A pod using this ServiceAccount exchanges its projected token
# for temporary STS credentials through this trust relationship alone -- no
# aws_iam_access_key, no static credential, is ever created.

data "aws_iam_policy_document" "portable_service_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.aws_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.aws_oidc_provider_url}:sub"
      values   = ["system:serviceaccount:${var.service_account_namespace}:${var.service_account_name}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.aws_oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "portable_service" {
  name               = "portable-service-irsa"
  assume_role_policy = data.aws_iam_policy_document.portable_service_assume.json
  tags               = var.tags
}

# Least-privilege, illustrative permission: read this workload's own config
# parameters, nothing else. A real workload's policy is specific to what it
# actually calls -- this exists to prove the binding compiles and attaches,
# not to be a template for every workload's permissions.
data "aws_iam_policy_document" "portable_service_permissions" {
  statement {
    sid       = "ReadOwnConfig"
    actions   = ["ssm:GetParameter", "ssm:GetParametersByPath"]
    resources = ["arn:aws:ssm:*:*:parameter/portable-service/*"]
  }
}

resource "aws_iam_role_policy" "portable_service" {
  name   = "portable-service-read-config"
  role   = aws_iam_role.portable_service.id
  policy = data.aws_iam_policy_document.portable_service_permissions.json
}
