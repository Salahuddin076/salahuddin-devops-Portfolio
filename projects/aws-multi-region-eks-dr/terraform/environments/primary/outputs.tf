output "cluster_name" {
  description = "EKS cluster name (aws eks update-kubeconfig --name ...)."
  value       = module.regional_stack.cluster_name
}

output "vpc_cidr" {
  description = "VPC CIDR for the chart's networkPolicy.albSourceCidrs."
  value       = module.regional_stack.vpc_cidr
}

output "data_subnet_cidrs" {
  description = "Data subnet CIDRs for the chart's networkPolicy.dataSubnetCidrs."
  value       = module.regional_stack.data_subnet_cidrs
}

output "cache_primary_endpoint" {
  description = "Valkey endpoint for the chart's config.cacheHost."
  value       = module.regional_stack.cache_primary_endpoint
}

output "global_data_inputs" {
  description = "Paste into environments/global as this region's object (primary or dr)."
  value = {
    kms_key_arn          = module.regional_stack.kms_key_arn
    db_subnet_group_name = module.regional_stack.db_subnet_group_name
    db_security_group_id = module.regional_stack.db_security_group_id
  }
}

output "lb_controller_role_arn" {
  description = "Role used by the AWS Load Balancer Controller through Pod Identity."
  value       = module.regional_stack.lb_controller_role_arn
}
