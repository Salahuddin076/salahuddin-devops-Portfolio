output "security_group_id" {
  description = "Security group ID for this zone."
  value       = aws_security_group.this.id
}

output "network_acl_id" {
  description = "Network ACL ID for this zone, or null if enable_network_acl is false."
  value       = try(aws_network_acl.this[0].id, null)
}

output "zone" {
  description = "Echoes var.zone, so callers can wire the edge SG id into the regulated zone's allowed_ingress without a separate lookup."
  value       = var.zone
}
