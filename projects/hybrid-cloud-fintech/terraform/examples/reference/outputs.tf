output "vpn_tunnel_count" {
  description = "Total IPsec tunnel count across both on-prem devices (expect 4: 2 connections x 2 tunnels each)."
  value       = module.connectivity.tunnel_count
}

output "vpn_connection_count" {
  description = "Independent VPN connections, one per on-prem device (expect 2)."
  value       = module.connectivity.connection_count
}

output "edge_security_group_id" {
  value = module.edge_zone.security_group_id
}

output "regulated_security_group_id" {
  value = module.regulated_zone.security_group_id
}

output "regulated_network_acl_id" {
  value = module.regulated_zone.network_acl_id
}
