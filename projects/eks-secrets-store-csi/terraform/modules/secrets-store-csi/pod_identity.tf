# The app's ServiceAccount gets an IAM role through EKS Pod Identity. ASCP
# calls Secrets Manager *as this pod's identity*, so the role is the
# boundary: it can read exactly these two secrets and decrypt with this key
# only through Secrets Manager. IRSA is the documented alternative
# (docs/decisions/0002-pod-identity-vs-irsa.md); it is not in code.

data "aws_eks_cluster" "this" {
  name = var.cluster_name
}

data "aws_iam_policy_document" "assume" {
  statement {
    sid     = "EksPodIdentity"
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [data.aws_eks_cluster.this.arn]
    }
  }
}

data "aws_iam_policy_document" "read_secrets" {
  statement {
    sid     = "ReadTheseTwoSecrets"
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [
      aws_secretsmanager_secret.db.arn,
      aws_secretsmanager_secret.api_key.arn,
    ]
  }

  statement {
    sid       = "DecryptOnlyViaSecretsManager"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.secrets.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${data.aws_region.current.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name                 = "${var.name}-secrets-reader"
  description          = "Pod Identity role for ${var.namespace}/${var.service_account}: read two secrets"
  assume_role_policy   = data.aws_iam_policy_document.assume.json
  max_session_duration = 3600
  tags                 = var.tags
}

resource "aws_iam_role_policy" "read_secrets" {
  name   = "read-app-secrets"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.read_secrets.json
}

resource "aws_eks_pod_identity_association" "app" {
  cluster_name    = var.cluster_name
  namespace       = var.namespace
  service_account = var.service_account
  role_arn        = aws_iam_role.app.arn
  tags            = var.tags

  depends_on = [aws_eks_addon.pod_identity_agent]
}
