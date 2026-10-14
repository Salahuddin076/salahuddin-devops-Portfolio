output "global_cluster_id" {
  description = "Aurora global cluster identifier. Also the failover CLI's --confirm token."
  value       = aws_rds_global_cluster.this.id
}

output "primary_cluster_arn" {
  description = "Aurora cluster ARN in the primary region."
  value       = aws_rds_cluster.primary.arn
}

output "dr_cluster_arn" {
  description = "Aurora cluster ARN in the DR region."
  value       = aws_rds_cluster.dr.arn
}

output "cluster_endpoints" {
  description = "Regional writer endpoints by region, for each region's values file (DB_HOST). A secondary's endpoint only accepts writes after promotion."
  value = {
    (local.primary_region) = aws_rds_cluster.primary.endpoint
    (local.dr_region)      = aws_rds_cluster.dr.endpoint
  }
}

output "reader_endpoints" {
  description = "Regional reader endpoints by region."
  value = {
    (local.primary_region) = aws_rds_cluster.primary.reader_endpoint
    (local.dr_region)      = aws_rds_cluster.dr.reader_endpoint
  }
}

output "secret_arn" {
  description = "Database secret ARN in the primary region (the DR replica has the same name)."
  value       = aws_secretsmanager_secret.db.arn
}

output "bucket_names" {
  description = "Application buckets by region."
  value = {
    (local.primary_region) = aws_s3_bucket.primary.bucket
    (local.dr_region)      = aws_s3_bucket.dr.bucket
  }
}

output "health_check_ids" {
  description = "Route 53 health check IDs by region (empty until phase 2 of the bootstrap)."
  value       = { for r, hc in aws_route53_health_check.regional : r => hc.id }
}

output "failover_config" {
  description = "Values for the failover CLI's config file (config/failover.example.json shape)."
  value = {
    global_cluster_id = aws_rds_global_cluster.this.id
    hosted_zone_id    = try(var.dns.hosted_zone_id, null)
    record_name       = try(var.dns.record_name, null)
    regions = {
      (local.primary_region) = {
        cluster_arn     = aws_rds_cluster.primary.arn
        cluster_id      = aws_rds_cluster.primary.cluster_identifier
        health_check_id = try(aws_route53_health_check.regional[local.primary_region].id, null)
        health_url      = local.dns_enabled ? "https://${local.primary_region}.${var.dns.record_name}${var.dns.health_check_path}" : null
      }
      (local.dr_region) = {
        cluster_arn     = aws_rds_cluster.dr.arn
        cluster_id      = aws_rds_cluster.dr.cluster_identifier
        health_check_id = try(aws_route53_health_check.regional[local.dr_region].id, null)
        health_url      = local.dns_enabled ? "https://${local.dr_region}.${var.dns.record_name}${var.dns.health_check_path}" : null
      }
    }
  }
}
