# EKS Pod Identity for the two workloads that call AWS APIs. Both roles trust
# pods.eks.amazonaws.com; the association pins each role to one namespace and
# service account in this cluster. No OIDC provider, no IRSA annotations.

data "aws_iam_policy_document" "pod_identity_assume" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    # Only Pod Identity sessions for this account and cluster.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_eks_cluster.this.arn]
    }
  }
}

# --- AWS Load Balancer Controller ----------------------------------------------
# The controller creates the ALB from the chart's Ingress. Terraform creates
# only its permissions; the ALB's DNS name is read after the first deploy and
# fed to the global-data module (see docs/operations.md, two-phase bootstrap).

resource "aws_iam_role" "lb_controller" {
  name               = "${var.name}-aws-lb-controller"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "lb_controller" {
  name   = "aws-load-balancer-controller"
  role   = aws_iam_role.lb_controller.id
  policy = templatefile("${path.module}/policies/aws-load-balancer-controller.json.tftpl", { partition = data.aws_partition.current.partition })
}

resource "aws_eks_pod_identity_association" "lb_controller" {
  cluster_name    = aws_eks_cluster.this.name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  role_arn        = aws_iam_role.lb_controller.arn
  tags            = var.tags

  depends_on = [aws_eks_addon.pod_identity_agent]
}

# --- order API -----------------------------------------------------------------
# Reads the replicated DB secret and its local bucket, decrypts with the local
# key. Everything is scoped to this region: a pod in us-west-2 never needs the
# us-east-1 copy, so it can't accidentally depend on the failed region.

locals {
  secret_arn_pattern = "arn:${data.aws_partition.current.partition}:secretsmanager:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:secret:${var.app_secret_name}-??????"
  app_bucket_arn     = "arn:${data.aws_partition.current.partition}:s3:::${var.app_bucket_name}"
}

data "aws_iam_policy_document" "app" {
  statement {
    sid       = "ReadDbSecret"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [local.secret_arn_pattern]
  }

  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket"]
    resources = [local.app_bucket_arn]
  }

  statement {
    sid       = "ReadWriteObjects"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${local.app_bucket_arn}/*"]
  }

  statement {
    sid       = "UseRegionalKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.this.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values = [
        "secretsmanager.${data.aws_region.current.region}.amazonaws.com",
        "s3.${data.aws_region.current.region}.amazonaws.com",
      ]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.name}-order-api"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "app" {
  name   = "order-api"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app.json
}

resource "aws_eks_pod_identity_association" "app" {
  cluster_name    = aws_eks_cluster.this.name
  namespace       = var.app_namespace
  service_account = var.app_service_account
  role_arn        = aws_iam_role.app.arn
  tags            = var.tags

  depends_on = [aws_eks_addon.pod_identity_agent]
}
