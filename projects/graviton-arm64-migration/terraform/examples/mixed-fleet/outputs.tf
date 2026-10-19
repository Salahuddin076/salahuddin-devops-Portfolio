output "node_groups" {
  description = "Node group name, architecture and ARN per pool."
  value = {
    for k, v in module.node_pool : k => {
      name         = v.node_group_name
      architecture = v.architecture
      arn          = v.node_group_arn
    }
  }
}

output "ecr_repository_url" {
  description = "Push the multi-arch manifest list here: docker buildx build --platform linux/amd64,linux/arm64 --push -t <ecr_repository_url>:<tag> ."
  value       = module.ecr.repository_url
}
