output "region" {
  description = "Region this stack was deployed to."
  value       = data.aws_region.current.region
}

output "vpc_id" {
  description = "VPC ID."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "VPC CIDR (the chart's NetworkPolicy allows ALB traffic from it)."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnets (tagged for the Load Balancer Controller)."
  value       = [for s in aws_subnet.public : s.id]
}

output "private_subnet_ids" {
  description = "Private subnets (EKS nodes and pods)."
  value       = [for s in aws_subnet.private : s.id]
}

output "data_subnet_cidrs" {
  description = "Data subnet CIDRs (the chart's NetworkPolicy allows DB and cache egress to them)."
  value       = [for s in aws_subnet.data : s.cidr_block]
}

output "cluster_name" {
  description = "EKS cluster name."
  value       = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  description = "EKS API endpoint."
  value       = aws_eks_cluster.this.endpoint
}

output "cluster_security_group_id" {
  description = "EKS cluster security group (nodes and pods)."
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}

output "kms_key_arn" {
  description = "Regional CMK. Pass to global-data for Aurora, S3 and Secrets Manager in this region."
  value       = aws_kms_key.this.arn
}

output "db_subnet_group_name" {
  description = "Aurora subnet group (data subnets). Pass to global-data."
  value       = aws_db_subnet_group.this.name
}

output "db_security_group_id" {
  description = "Aurora security group. Pass to global-data."
  value       = aws_security_group.db.id
}

output "cache_primary_endpoint" {
  description = "Valkey primary endpoint for the chart's values file."
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "app_role_arn" {
  description = "Order API role (Pod Identity)."
  value       = aws_iam_role.app.arn
}

output "lb_controller_role_arn" {
  description = "AWS Load Balancer Controller role (Pod Identity)."
  value       = aws_iam_role.lb_controller.arn
}
