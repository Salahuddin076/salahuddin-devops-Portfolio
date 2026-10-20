output "vnet_id" {
  description = "Hub VNet resource ID, used by the spoke module to create the hub->spoke peering half."
  value       = azurerm_virtual_network.hub.id
}

output "vnet_name" {
  description = "Hub VNet name."
  value       = azurerm_virtual_network.hub.name
}

output "firewall_private_ip" {
  description = "Azure Firewall's private IP -- the next hop every spoke's forced-tunneling route points at."
  value       = azurerm_firewall.this.ip_configuration[0].private_ip_address
}

output "firewall_policy_id" {
  description = "Firewall policy ID, so spokes (or additional rule collection groups) can be wired to the same shared policy."
  value       = azurerm_firewall_policy.this.id
}
