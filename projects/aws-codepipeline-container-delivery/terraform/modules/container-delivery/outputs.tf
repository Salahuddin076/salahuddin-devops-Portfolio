output "pipeline_name" {
  description = "CodePipeline name."
  value       = aws_codepipeline.this.name
}

output "connection_arn" {
  description = "CodeConnections connection. Starts PENDING: complete the GitHub handshake in the console once."
  value       = aws_codeconnections_connection.github.arn
}

output "ecr_repository_url" {
  description = "ECR repository the build pushes commit-SHA tags to."
  value       = aws_ecr_repository.app.repository_url
}

output "artifact_bucket" {
  description = "Pipeline artifact bucket (SSE-KMS, TLS only, no public access)."
  value       = aws_s3_bucket.artifacts.bucket
}

output "cluster_name" {
  description = "ECS cluster running both services."
  value       = aws_ecs_cluster.this.name
}

output "service_names" {
  description = "ECS service name per environment."
  value       = { for k, s in aws_ecs_service.app : k => s.name }
}

output "db_secret_arns" {
  description = "DB secret per environment. Set the value out of band: {\"username\": ..., \"password\": ...}."
  value       = { for k, s in aws_secretsmanager_secret.db : k => s.arn }
}

output "registry_secret_arn" {
  description = "Docker Hub credentials secret read by the build stage. Set the value out of band."
  value       = aws_secretsmanager_secret.registry.arn
}

output "approval_topic_arn" {
  description = "SNS topic notified when a release waits for prod approval."
  value       = aws_sns_topic.approval.arn
}

output "kms_key_arn" {
  description = "Customer managed key used by the stack."
  value       = aws_kms_key.this.arn
}

output "codebuild_project_names" {
  description = "CodeBuild project per stage."
  value       = { for k, p in aws_codebuild_project.this : k => p.name }
}
