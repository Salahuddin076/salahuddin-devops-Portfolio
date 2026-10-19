output "repository_arn" {
  description = "ARN of the ECR repository."
  value       = aws_ecr_repository.this.arn
}

output "repository_url" {
  description = "Pull/push URL, e.g. for `docker buildx build --push -t <repository_url>:<tag>`."
  value       = aws_ecr_repository.this.repository_url
}

output "repository_name" {
  description = "Repository name, as referenced by the lifecycle policy and by IAM resource ARNs."
  value       = aws_ecr_repository.this.name
}
