variable "resource_group_name" {
  description = "Resource group the spoke VNet and its subnets are created in."
  type        = string
}

variable "location" {
  description = "Azure region for the spoke resources."
  type        = string
}

variable "name_prefix" {
  description = "Prefix applied to every spoke resource name (e.g. 'example-spoke')."
  type        = string
}

variable "spoke_vnet_cidr" {
  description = "CIDR for the spoke VNet."
  type        = string
  default     = "10.1.0.0/16"
}

variable "aks_subnet_cidr" {
  description = "CIDR for the subnet the AKS node pools attach to."
  type        = string
  default     = "10.1.0.0/22"
}

variable "private_endpoints_subnet_cidr" {
  description = "CIDR for the subnet holding ACR and Key Vault private endpoints."
  type        = string
  default     = "10.1.4.0/24"
}

variable "hub_vnet_id" {
  description = "Hub VNet resource ID, to create the spoke->hub half of the peering."
  type        = string
}

variable "hub_vnet_name" {
  description = "Hub VNet name, used to create the hub->spoke half of the peering from this module."
  type        = string
}

variable "hub_resource_group_name" {
  description = "Resource group the hub VNet lives in (may differ from this spoke's resource group)."
  type        = string
}

variable "firewall_private_ip" {
  description = "Azure Firewall's private IP in the hub. The spoke's default route is forced-tunneled here instead of to the internet directly."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
  default     = {}
}
