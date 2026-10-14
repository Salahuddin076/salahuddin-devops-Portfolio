output "transit_gateway_id" {
  description = "Transit Gateway ID (input to workload-baseline)."
  value       = module.network_hub.transit_gateway_id
}

output "route_table_ids" {
  description = "Environment -> TGW route table ID."
  value       = module.network_hub.route_table_ids
}

output "propagation_matrix" {
  description = "Which route tables each environment's routes reach."
  value       = module.network_hub.propagation_matrix
}

output "nat_gateway_public_ips" {
  description = "Egress public IPs."
  value       = module.network_hub.nat_gateway_public_ips
}
