output "cluster_name" {
  description = "ECS cluster name."
  value       = module.platform.cluster_name
}

output "ecr_repository_url" {
  description = "Push commit-SHA-tagged images here."
  value       = module.platform.ecr_repository_url
}
