output "vpn_gateway_id" {
  description = "Virtual Private Gateway ID, attached to the VPC."
  value       = aws_vpn_gateway.this.id
}

output "customer_gateway_ids" {
  description = "Customer Gateway ID per on-prem device name."
  value       = { for k, v in aws_customer_gateway.this : k => v.id }
}

output "vpn_connection_ids" {
  description = "VPN Connection ID per on-prem device name (one connection, two tunnels, per device)."
  value       = { for k, v in aws_vpn_connection.this : k => v.id }
}

output "tunnel_count" {
  description = "Total number of IPsec tunnels across every VPN connection (used by tests/CI to assert redundancy, not just connection count)."
  value       = length(aws_vpn_connection.this) * 2
}

output "connection_count" {
  description = "Number of independent VPN connections (one per on-prem device)."
  value       = length(aws_vpn_connection.this)
}
