variable "resource_group_name" {
  description = "Resource group the hub VNet, Azure Firewall and Bastion are created in."
  type        = string
}

variable "location" {
  description = "Azure region for the hub resources."
  type        = string
}

variable "name_prefix" {
  description = "Prefix applied to every hub resource name (e.g. 'example-hub')."
  type        = string
}

variable "hub_vnet_cidr" {
  description = "CIDR for the hub VNet. Synthetic documentation range by default."
  type        = string
  default     = "10.0.0.0/22"
}

variable "firewall_subnet_cidr" {
  description = "CIDR for AzureFirewallSubnet (name is fixed by the platform, must be /26 or larger)."
  type        = string
  default     = "10.0.0.0/26"
}

variable "bastion_subnet_cidr" {
  description = "CIDR for AzureBastionSubnet (name is fixed by the platform, must be /26 or larger)."
  type        = string
  default     = "10.0.0.64/26"
}

variable "firewall_sku_tier" {
  description = "Azure Firewall SKU tier. Standard is the cost-sensible default; Premium adds TLS inspection/IDPS."
  type        = string
  default     = "Standard"
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
  default     = {}
}
