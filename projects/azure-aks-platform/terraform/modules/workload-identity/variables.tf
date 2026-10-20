variable "resource_group_name" {
  description = "Resource group for the user-assigned managed identity."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "oidc_issuer_url" {
  description = "AKS cluster's OIDC issuer URL (module.aks.oidc_issuer_url) -- the federated credential's trust anchor."
  type        = string
}

variable "workloads" {
  description = "One federated identity per pod ServiceAccount that should authenticate as an Entra identity with Microsoft Entra Workload ID -- no secret, no certificate, no google_service_account_key-style downloaded credential."
  type = map(object({
    namespace            = string
    service_account_name = string
  }))
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
  default     = {}
}
