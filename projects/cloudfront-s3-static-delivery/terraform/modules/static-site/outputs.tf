output "bucket_name" {
  description = "Origin bucket name (the deploy target)."
  value       = aws_s3_bucket.origin.id
}

output "bucket_arn" {
  description = "Origin bucket ARN (input to the github-oidc-deployer module)."
  value       = aws_s3_bucket.origin.arn
}

output "distribution_id" {
  description = "CloudFront distribution ID (used by create-invalidation)."
  value       = aws_cloudfront_distribution.this.id
}

output "distribution_arn" {
  description = "CloudFront distribution ARN (input to the github-oidc-deployer module, and the AWS:SourceArn in the bucket policy)."
  value       = aws_cloudfront_distribution.this.arn
}

output "distribution_domain_name" {
  description = "The *.cloudfront.net name, useful for testing before DNS changes propagate."
  value       = aws_cloudfront_distribution.this.domain_name
}

output "site_urls" {
  description = "HTTPS URLs for every configured hostname."
  value       = [for d in var.domain_names : "https://${d}/"]
}

output "certificate_arn" {
  description = "ACM certificate ARN (us-east-1)."
  value       = aws_acm_certificate.this.arn
}

output "response_headers_policy_id" {
  description = "Security headers policy, reusable on additional cache behaviours."
  value       = aws_cloudfront_response_headers_policy.security.id
}

output "cache_policy_id" {
  description = "ID of the managed CachingOptimized policy, resolved by name at plan time."
  value       = data.aws_cloudfront_cache_policy.caching_optimized.id
}

output "access_log_group_name" {
  description = "CloudWatch log group receiving CloudFront access logs (us-east-1), or null when logging is off."
  value       = local.logging_enabled ? aws_cloudwatch_log_group.access[0].name : null
}

output "kms_key_policy_statement" {
  description = "When kms_key_arn is set: the statement to add to that key's policy so CloudFront (through OAC) can decrypt objects for this distribution only. Null for SSE-S3."
  value = var.kms_key_arn == null ? null : jsonencode({
    Sid       = "AllowCloudFrontOACDecrypt"
    Effect    = "Allow"
    Principal = { Service = "cloudfront.amazonaws.com" }
    Action    = ["kms:Decrypt"]
    Resource  = "*"
    Condition = {
      StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.this.arn }
    }
  })
}
