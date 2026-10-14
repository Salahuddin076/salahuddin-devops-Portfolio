output "pipeline_name" {
  description = "CodePipeline name."
  value       = module.delivery.pipeline_name
}

output "connection_arn" {
  description = "Complete the GitHub handshake for this connection in the console before the first run."
  value       = module.delivery.connection_arn
}

output "ecr_repository_url" {
  description = "ECR repository."
  value       = module.delivery.ecr_repository_url
}

output "service_names" {
  description = "ECS services (staging, prod)."
  value       = module.delivery.service_names
}

output "db_secret_arns" {
  description = "Set these secret values out of band before setting first_apply = false."
  value       = module.delivery.db_secret_arns
}

output "registry_secret_arn" {
  description = "Set the Docker Hub credentials out of band before the first pipeline run."
  value       = module.delivery.registry_secret_arn
}
