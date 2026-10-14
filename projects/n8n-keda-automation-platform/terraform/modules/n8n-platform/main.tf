data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "aws_eks_cluster" "this" {
  name = var.cluster_name
}

data "aws_vpc" "this" {
  id = var.vpc_id
}

locals {
  client_security_group_ids = concat([aws_security_group.n8n_pods.id], var.additional_client_security_group_ids)
}

# One customer-managed key for the three secrets, the RDS-managed master
# secret, RDS storage and ElastiCache at rest.
resource "aws_kms_key" "n8n" {
  description             = "${var.name}: n8n secrets, RDS and ElastiCache encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = var.tags
}

resource "aws_kms_alias" "n8n" {
  name          = "alias/${var.name}"
  target_key_id = aws_kms_key.n8n.key_id
}
