output "vnet_id" {
  description = "Spoke VNet resource ID."
  value       = azurerm_virtual_network.spoke.id
}

output "aks_subnet_id" {
  description = "Subnet ID the AKS node pools attach to."
  value       = azurerm_subnet.aks.id
}

output "private_endpoints_subnet_id" {
  description = "Subnet ID for ACR and Key Vault private endpoints."
  value       = azurerm_subnet.private_endpoints.id
}

output "route_table_id" {
  description = "Forced-tunneling route table ID, so the AKS module can grant its control-plane identity Network Contributor on it (required for outbound_type=userDefinedRouting)."
  value       = azurerm_route_table.forced_tunnel.id
}
