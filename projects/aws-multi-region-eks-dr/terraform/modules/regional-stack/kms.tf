data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

# One customer managed key per region. It encrypts this region's EKS secrets,
# Valkey, and (passed to global-data) the regional Aurora cluster, S3 bucket
# and Secrets Manager secret or replica. Keys are deliberately not
# multi-Region keys: a compromised or deleted key in one region must not
# reach the other (see docs/security.md).
data "aws_iam_policy_document" "kms" {
  statement {
    sid       = "AccountRootAdministers"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  # CloudWatch Logs encrypts the EKS control plane log group with this key.
  statement {
    sid = "CloudWatchLogs"
    actions = [
      "kms:Encrypt*",
      "kms:Decrypt*",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:Describe*",
    ]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["logs.${data.aws_region.current.region}.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/eks/${local.cluster_name}/*"]
    }
  }
}

resource "aws_kms_key" "this" {
  description             = "${var.name}: EKS secrets, Aurora, S3, Valkey, Secrets Manager (${var.role} region)"
  enable_key_rotation     = true
  deletion_window_in_days = var.kms_deletion_window_days
  policy                  = data.aws_iam_policy_document.kms.json

  tags = merge(var.tags, { Name = "${var.name}-cmk" })
}

resource "aws_kms_alias" "this" {
  name          = "alias/${var.name}"
  target_key_id = aws_kms_key.this.key_id
}
