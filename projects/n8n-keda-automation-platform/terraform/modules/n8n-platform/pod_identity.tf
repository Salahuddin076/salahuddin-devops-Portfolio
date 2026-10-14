# Two Pod Identity roles, each scoped to exactly what its pods read:
#   n8n   (namespace/service_account)  the three n8n secrets, via ASCP
#   keda  (keda/keda-operator)         the Redis AUTH token only, for the scaler
# Neither can read the RDS-managed master secret.

data "aws_iam_policy_document" "pod_identity_trust" {
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

data "aws_iam_policy_document" "n8n" {
  statement {
    sid     = "ReadN8nSecrets"
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [
      aws_secretsmanager_secret.encryption_key.arn,
      aws_secretsmanager_secret.db_app.arn,
      aws_secretsmanager_secret.redis_auth.arn,
    ]
  }

  statement {
    sid       = "DecryptOnlyViaSecretsManager"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.n8n.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${data.aws_region.current.region}.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "keda" {
  statement {
    sid       = "ReadRedisAuthOnly"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.redis_auth.arn]
  }

  statement {
    sid       = "DecryptOnlyViaSecretsManager"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.n8n.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${data.aws_region.current.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "n8n" {
  name                 = "${var.name}-n8n-secrets"
  description          = "Pod Identity: ${var.namespace}/${var.service_account} reads the n8n secrets"
  assume_role_policy   = data.aws_iam_policy_document.pod_identity_trust.json
  max_session_duration = 3600
  tags                 = var.tags
}

resource "aws_iam_role_policy" "n8n" {
  name   = "read-n8n-secrets"
  role   = aws_iam_role.n8n.id
  policy = data.aws_iam_policy_document.n8n.json
}

resource "aws_eks_pod_identity_association" "n8n" {
  cluster_name    = var.cluster_name
  namespace       = var.namespace
  service_account = var.service_account
  role_arn        = aws_iam_role.n8n.arn
  tags            = var.tags
}

resource "aws_iam_role" "keda" {
  name                 = "${var.name}-keda-redis-auth"
  description          = "Pod Identity: ${var.keda_namespace}/${var.keda_service_account} reads the Redis AUTH token"
  assume_role_policy   = data.aws_iam_policy_document.pod_identity_trust.json
  max_session_duration = 3600
  tags                 = var.tags
}

resource "aws_iam_role_policy" "keda" {
  name   = "read-redis-auth"
  role   = aws_iam_role.keda.id
  policy = data.aws_iam_policy_document.keda.json
}

resource "aws_eks_pod_identity_association" "keda" {
  cluster_name    = var.cluster_name
  namespace       = var.keda_namespace
  service_account = var.keda_service_account
  role_arn        = aws_iam_role.keda.arn
  tags            = var.tags
}
