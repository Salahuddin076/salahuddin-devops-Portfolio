# Spoke VNet: where the private AKS cluster and its private endpoints live.
# Everything that leaves this VNet and isn't destined for the hub or
# Microsoft's backbone (private endpoint traffic never leaves the Microsoft
# network at all) is forced through the hub firewall by the route table
# below -- there is deliberately no NAT gateway, no public IP, and no
# default-route-to-internet here.

resource "azurerm_virtual_network" "spoke" {
  name                = "${var.name_prefix}-vnet"
  resource_group_name = var.resource_group_name
  location            = var.location
  address_space       = [var.spoke_vnet_cidr]
  tags                = var.tags
}

resource "azurerm_route_table" "forced_tunnel" {
  name                          = "${var.name_prefix}-rt"
  resource_group_name           = var.resource_group_name
  location                      = var.location
  bgp_route_propagation_enabled = false
  tags                          = var.tags

  route {
    name                   = "default-via-firewall"
    address_prefix         = "0.0.0.0/0"
    next_hop_type          = "VirtualAppliance"
    next_hop_in_ip_address = var.firewall_private_ip
  }
}

resource "azurerm_subnet" "aks" {
  name                 = "${var.name_prefix}-aks-subnet"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.spoke.name
  address_prefixes     = [var.aks_subnet_cidr]
}

resource "azurerm_subnet_route_table_association" "aks" {
  subnet_id      = azurerm_subnet.aks.id
  route_table_id = azurerm_route_table.forced_tunnel.id
}

# Private endpoints don't need forced tunneling (their traffic rides the
# Microsoft backbone, never a public path) but they do need to be isolated
# from the node subnet's NSG rules, hence a dedicated subnet.
resource "azurerm_subnet" "private_endpoints" {
  name                 = "${var.name_prefix}-pe-subnet"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.spoke.name
  address_prefixes     = [var.private_endpoints_subnet_cidr]

  private_endpoint_network_policies = "Disabled"
}

resource "azurerm_network_security_group" "aks" {
  name                = "${var.name_prefix}-aks-nsg"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

resource "azurerm_subnet_network_security_group_association" "aks" {
  subnet_id                 = azurerm_subnet.aks.id
  network_security_group_id = azurerm_network_security_group.aks.id
}

# Spoke -> hub half of the peering, created here. The hub -> spoke half is
# also declared in this module (rather than in the hub module) so that
# adding a new spoke never requires re-planning the hub's own state -- the
# hub module stays spoke-count-agnostic, which matters once there is more
# than one spoke sharing the firewall (see docs/cost.md).
resource "azurerm_virtual_network_peering" "spoke_to_hub" {
  name                      = "${var.name_prefix}-to-hub"
  resource_group_name       = var.resource_group_name
  virtual_network_name      = azurerm_virtual_network.spoke.name
  remote_virtual_network_id = var.hub_vnet_id

  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
  allow_gateway_transit        = false
  use_remote_gateways          = false
}

resource "azurerm_virtual_network_peering" "hub_to_spoke" {
  name                      = "hub-to-${var.name_prefix}"
  resource_group_name       = var.hub_resource_group_name
  virtual_network_name      = var.hub_vnet_name
  remote_virtual_network_id = azurerm_virtual_network.spoke.id

  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
  allow_gateway_transit        = false
  use_remote_gateways          = false
}
