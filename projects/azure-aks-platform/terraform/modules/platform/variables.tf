variable "resource_group_name" {
  description = "Resource group for ACR, Key Vault and Log Analytics."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "name_prefix" {
  description = "Prefix applied to ACR, Key Vault and Log Analytics names (must be globally-unique-safe for ACR/Key Vault, so keep it short)."
  type        = string
}

variable "tenant_id" {
  description = "Entra tenant ID for Key Vault's access policy/RBAC scoping."
  type        = string
}

variable "vnet_id" {
  description = "Spoke VNet ID, linked to the private DNS zones so cluster-internal DNS resolves the private endpoints."
  type        = string
}

variable "private_endpoints_subnet_id" {
  description = "Subnet the ACR and Key Vault private endpoints attach to."
  type        = string
}

variable "log_analytics_retention_in_days" {
  description = "Log Analytics workspace retention."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
  default     = {}
}
