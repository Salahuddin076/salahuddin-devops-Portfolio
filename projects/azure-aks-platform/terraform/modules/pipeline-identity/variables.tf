variable "display_name" {
  description = "Display name for the Entra app registration backing the Azure DevOps service connection."
  type        = string
}

variable "ado_organization" {
  description = "Azure DevOps organization name. Synthetic placeholder in the reference example -- never a real org."
  type        = string
}

variable "ado_project_id" {
  description = "Azure DevOps project ID (a GUID, visible in Project Settings). Synthetic placeholder in the reference example."
  type        = string
}

variable "ado_service_connection_id" {
  description = "Azure DevOps service connection ID (a GUID, assigned when the service connection is created). Synthetic placeholder in the reference example -- there is a bootstrapping order dependency here: the service connection is normally created first (workload-identity-federation type, no secret), which allocates this ID, and *that* ID is what this federated credential's subject must match."
  type        = string
}

variable "acr_id" {
  description = "Container registry resource ID the pipeline identity is allowed to push images to."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
  default     = {}
}
