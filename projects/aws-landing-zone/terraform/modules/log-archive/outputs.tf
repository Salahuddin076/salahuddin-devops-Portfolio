output "bucket_name" {
  description = "Central log bucket name."
  value       = aws_s3_bucket.logs.id
}

output "bucket_arn" {
  description = "Central log bucket ARN."
  value       = aws_s3_bucket.logs.arn
}

output "kms_key_arn" {
  description = "KMS key for CloudTrail and Config log encryption."
  value       = aws_kms_key.logs.arn
}

output "trail_arn" {
  description = "Organization trail ARN."
  value       = aws_cloudtrail.org.arn
}

output "config_aggregator_arn" {
  description = "Organization Config aggregator ARN."
  value       = aws_config_configuration_aggregator.org.arn
}
