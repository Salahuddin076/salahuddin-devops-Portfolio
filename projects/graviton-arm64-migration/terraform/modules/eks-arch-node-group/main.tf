# A managed node group whose architecture is a variable, not a fork in the
# code. `architecture = "arm64"` is the entire diff between an x86 pool and a
# Graviton pool: it picks the AL2023 AMI family and the matching instance
# family, and EKS sets kubernetes.io/arch on every node from the AMI itself
# (not from a label Terraform could get out of sync). Scheduling workloads
# onto the pool is a separate step (nodeSelector/affinity in
# helm/multiarch-app), so a pool can exist, join the cluster and pass
# compatibility testing before a single pod runs on it.

locals {
  arch_defaults = {
    amd64 = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m6i.large", "c6i.large"]
    }
    arm64 = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = ["m7g.large", "c7g.large"]
    }
  }

  ami_type       = local.arch_defaults[var.architecture].ami_type
  instance_types = coalesce(var.instance_types, local.arch_defaults[var.architecture].instance_types)

  labels = merge(
    { "kubernetes.io/arch" = var.architecture },
    var.extra_labels,
  )
}

data "aws_partition" "current" {}

data "aws_iam_policy_document" "node_assume" {
  count = var.node_role_arn == null ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  count = var.node_role_arn == null ? 1 : 0

  name               = "${var.name}-${var.architecture}-eks-node"
  assume_role_policy = data.aws_iam_policy_document.node_assume[0].json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = var.node_role_arn == null ? toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEC2ContainerRegistryReadOnly",
    "AmazonEKS_CNI_Policy",
  ]) : toset([])

  role       = aws_iam_role.node[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/${each.value}"
}

data "aws_iam_policy_document" "extra_ecr" {
  count = length(var.ecr_repository_arns) > 0 ? 1 : 0

  statement {
    sid       = "PullScopedRepositories"
    actions   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability"]
    resources = var.ecr_repository_arns
  }
}

resource "aws_iam_role_policy" "extra_ecr" {
  count = var.node_role_arn == null && length(var.ecr_repository_arns) > 0 ? 1 : 0

  name   = "scoped-ecr-pull"
  role   = aws_iam_role.node[0].name
  policy = data.aws_iam_policy_document.extra_ecr[0].json
}

resource "aws_eks_node_group" "this" {
  cluster_name    = var.cluster_name
  node_group_name = "${var.name}-${var.architecture}"
  node_role_arn   = coalesce(var.node_role_arn, try(aws_iam_role.node[0].arn, null))
  subnet_ids      = var.subnet_ids
  ami_type        = local.ami_type
  instance_types  = local.instance_types
  capacity_type   = var.capacity_type

  scaling_config {
    min_size     = var.scaling_config.min_size
    desired_size = var.scaling_config.desired_size
    max_size     = var.scaling_config.max_size
  }

  update_config {
    max_unavailable_percentage = 33
  }

  labels = local.labels

  dynamic "taint" {
    for_each = var.taint == null ? [] : [var.taint]
    content {
      key    = taint.value.key
      value  = taint.value.value
      effect = taint.value.effect
    }
  }

  # A runbook or Cluster Autoscaler changes desired_size during the
  # migration (scaling Graviton up, x86 down); don't let the next apply
  # fight that.
  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }

  tags = merge(var.tags, { Architecture = var.architecture })

  depends_on = [aws_iam_role_policy_attachment.node]
}
