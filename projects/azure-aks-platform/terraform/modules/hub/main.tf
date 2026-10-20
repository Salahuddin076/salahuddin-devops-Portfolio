# Hub VNet: the single egress choke point shared by every spoke. A spoke
# never gets its own NAT gateway or public IP for outbound traffic -- it
# force-tunnels its default route to the firewall's private IP (see the
# `spoke` module), so every byte leaving any spoke is centrally logged and
# filtered here, in one place, by one team.

resource "azurerm_virtual_network" "hub" {
  name                = "${var.name_prefix}-vnet"
  resource_group_name = var.resource_group_name
  location            = var.location
  address_space       = [var.hub_vnet_cidr]
  tags                = var.tags
}

# Name is fixed by the platform -- Azure Firewall only looks for a subnet
# called exactly "AzureFirewallSubnet".
resource "azurerm_subnet" "firewall" {
  name                 = "AzureFirewallSubnet"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.hub.name
  address_prefixes     = [var.firewall_subnet_cidr]
}

# Same constraint for Bastion: the subnet name is fixed.
resource "azurerm_subnet" "bastion" {
  name                 = "AzureBastionSubnet"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.hub.name
  address_prefixes     = [var.bastion_subnet_cidr]
}

resource "azurerm_public_ip" "firewall" {
  name                = "${var.name_prefix}-fw-pip"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

resource "azurerm_public_ip" "bastion" {
  name                = "${var.name_prefix}-bastion-pip"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

# Policy-based firewall (the current azurerm-recommended shape, vs. the
# legacy inline rule_collection blocks on azurerm_firewall itself). Default
# posture is deny: nothing is allowed out until a rule collection says so.
resource "azurerm_firewall_policy" "this" {
  name                = "${var.name_prefix}-fw-policy"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = var.firewall_sku_tier
  tags                = var.tags
}

# One illustrative allow rule: AKS node/control-plane egress needs a small,
# well-known set of FQDNs (Microsoft Container Registry, AKS API, Azure
# Monitor). Everything else is denied by the policy's implicit default.
# A real deployment pins the full AKS "required network rules" FQDN list
# published by Microsoft; this is a documented placeholder, not that list.
resource "azurerm_firewall_policy_rule_collection_group" "aks_egress" {
  name               = "${var.name_prefix}-aks-egress"
  firewall_policy_id = azurerm_firewall_policy.this.id
  priority           = 200

  application_rule_collection {
    name     = "aks-required-fqdns"
    priority = 200
    action   = "Allow"

    rule {
      name = "aks-platform-fqdns"
      protocols {
        type = "Https"
        port = 443
      }
      source_addresses = [var.hub_vnet_cidr]
      destination_fqdns = [
        "*.hcp.${var.location}.azmk8s.io",
        "mcr.microsoft.com",
        "*.data.mcr.microsoft.com",
        "management.azure.com",
        "login.microsoftonline.com",
      ]
    }
  }
}

resource "azurerm_firewall" "this" {
  name                = "${var.name_prefix}-fw"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku_name            = "AZFW_VNet"
  sku_tier            = var.firewall_sku_tier
  firewall_policy_id  = azurerm_firewall_policy.this.id
  tags                = var.tags

  ip_configuration {
    name                 = "fw-ipconfig"
    subnet_id            = azurerm_subnet.firewall.id
    public_ip_address_id = azurerm_public_ip.firewall.id
  }
}

# Bastion: the only way an operator reaches a private AKS node or a jump
# box in a spoke, without putting a public IP or an SSH NSG rule on
# anything in the spoke itself.
resource "azurerm_bastion_host" "this" {
  name                = "${var.name_prefix}-bastion"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Standard"
  tags                = var.tags

  ip_configuration {
    name                 = "bastion-ipconfig"
    subnet_id            = azurerm_subnet.bastion.id
    public_ip_address_id = azurerm_public_ip.bastion.id
  }
}
