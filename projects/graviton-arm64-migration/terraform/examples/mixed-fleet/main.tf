# A mixed fleet on one existing cluster: an x86 pool workloads already run
# on, and a Graviton pool sized for the migration. Both pools exist and can
# pass compatibility testing before any pod is scheduled onto arm64 -- that
# scheduling decision lives in helm/multiarch-app, not here.

module "node_pool" {
  source = "../../modules/eks-arch-node-group"

  for_each = var.node_pools

  name                = each.key
  cluster_name        = var.cluster_name
  architecture        = each.value.architecture
  subnet_ids          = var.subnet_ids
  scaling_config      = each.value.scaling_config
  capacity_type       = each.value.capacity_type
  ecr_repository_arns = [module.ecr.repository_arn]
}

module "ecr" {
  source = "../../modules/ecr-multiarch"

  name                       = var.ecr_repository_name
  image_tag_mutability       = "IMMUTABLE"
  scan_on_push               = true
  untagged_image_expiry_days = 14
}
