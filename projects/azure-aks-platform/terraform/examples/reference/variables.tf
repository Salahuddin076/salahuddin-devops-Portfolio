variable "subscription_id" {
  description = "Azure subscription ID. Synthetic placeholder -- never a real subscription."
  type        = string
  default     = "00000000-0000-0000-0000-000000000000"
}

variable "tenant_id" {
  description = "Entra tenant ID. Synthetic placeholder -- never a real tenant."
  type        = string
  default     = "11111111-1111-1111-1111-111111111111"
}

variable "location" {
  description = "Azure region for every resource."
  type        = string
  default     = "eastus2"
}

variable "name_prefix" {
  description = "Prefix applied to resource names across the reference deployment."
  type        = string
  default     = "example-aks-platform"
}

variable "admin_group_object_ids" {
  description = "Entra ID group object IDs granted cluster-admin via Azure RBAC for Kubernetes Authorization. Synthetic GUID -- never a real tenant's group."
  type        = list(string)
  default     = ["22222222-2222-2222-2222-222222222222"]
}

variable "ado_organization" {
  description = "Azure DevOps organization name. Synthetic placeholder."
  type        = string
  default     = "example-org"
}

variable "ado_project_id" {
  description = "Azure DevOps project ID (GUID). Synthetic placeholder."
  type        = string
  default     = "33333333-3333-3333-3333-333333333333"
}

variable "ado_service_connection_id" {
  description = "Azure DevOps service connection ID (GUID). Synthetic placeholder."
  type        = string
  default     = "44444444-4444-4444-4444-444444444444"
}
