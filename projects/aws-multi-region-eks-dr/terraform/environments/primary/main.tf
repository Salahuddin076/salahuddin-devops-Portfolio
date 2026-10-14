# One regional stack: VPC, EKS, Valkey, KMS, Pod Identity roles. The same
# module is instantiated by environments/primary and environments/dr with
# different sizes; each has its own state so either region can be changed
# while the other is unreachable (docs/decisions/0004-terraform-layout.md).

locals {
  role = "primary"
}

module "regional_stack" {
  source = "../../modules/regional-stack"

  name = "${var.app_name}-${var.region}"
  role = local.role

  vpc_cidr           = var.vpc_cidr
  nat_gateway_per_az = var.nat_gateway_per_az

  kubernetes_version           = var.kubernetes_version
  endpoint_public_access_cidrs = var.endpoint_public_access_cidrs
  node_instance_types          = var.node_instance_types
  node_scaling                 = var.node_scaling
  cluster_admin_principal_arns = var.cluster_admin_principal_arns

  app_bucket_name = var.app_bucket_name
  app_secret_name = var.app_secret_name

  cache_node_type = var.cache_node_type
  cache_nodes     = var.cache_nodes
}
