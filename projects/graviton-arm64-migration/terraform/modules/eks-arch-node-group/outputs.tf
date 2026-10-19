output "node_group_arn" {
  description = "ARN of the managed node group."
  value       = aws_eks_node_group.this.arn
}

output "node_group_name" {
  description = "Node group name (\"<name>-<architecture>\")."
  value       = aws_eks_node_group.this.node_group_name
}

output "architecture" {
  description = "Architecture this pool was created for (amd64 or arm64)."
  value       = var.architecture
}

output "node_role_arn" {
  description = "IAM role ARN used by this node group's instances."
  value       = coalesce(var.node_role_arn, try(aws_iam_role.node[0].arn, null))
}
