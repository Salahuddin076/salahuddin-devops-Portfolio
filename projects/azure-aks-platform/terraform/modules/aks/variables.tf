variable "resource_group_name" {
  description = "Resource group the AKS cluster is created in."
  type        = string
}

variable "location" {
  description = "Azure region for the cluster."
  type        = string
}

variable "cluster_name" {
  description = "AKS cluster name."
  type        = string
}

variable "dns_prefix" {
  description = "DNS prefix for the private cluster's API server FQDN."
  type        = string
}

variable "kubernetes_version" {
  description = "Kubernetes minor version. Left unpinned to AKS's default channel unless set, so patch upgrades keep flowing."
  type        = string
  default     = null
}

variable "vnet_subnet_id" {
  description = "Spoke subnet ID the node pools attach to (module.spoke.aks_subnet_id)."
  type        = string
}

variable "route_table_id" {
  description = "Spoke route table ID (module.spoke.route_table_id). With outbound_type=userDefinedRouting, AKS's control-plane identity must hold Network Contributor here -- it manages the UDR'd subnet's association but relies on the spoke module, not itself, to own the default route to the firewall."
  type        = string
}

variable "admin_group_object_ids" {
  description = "Entra ID group object IDs granted cluster-admin via Azure RBAC for Kubernetes Authorization. Synthetic GUIDs in the reference example -- never a real tenant's group."
  type        = list(string)
  default     = []
}

variable "tenant_id" {
  description = "Entra tenant ID used for AKS-managed Entra integration and Azure RBAC."
  type        = string
}

variable "system_node_pool" {
  description = "System pool sizing: only runs critical add-ons, never application workloads."
  type = object({
    vm_size    = string
    node_count = number
    min_count  = number
    max_count  = number
    zones      = list(string)
  })
  default = {
    vm_size    = "Standard_D4s_v5"
    node_count = 3
    min_count  = 3
    max_count  = 5
    zones      = ["1", "2", "3"]
  }
}

variable "user_node_pools" {
  description = "Application node pools keyed by name, each its own `azurerm_kubernetes_cluster_node_pool`. Set `spot = true` and `priority = \"Spot\"` for interruptible workloads."
  type = map(object({
    vm_size        = string
    node_count     = number
    min_count      = number
    max_count      = number
    zones          = list(string)
    spot           = bool
    spot_max_price = optional(number)
    node_taints    = optional(list(string), [])
    node_labels    = optional(map(string), {})
  }))
  default = {
    user = {
      vm_size    = "Standard_D4s_v5"
      node_count = 2
      min_count  = 2
      max_count  = 10
      zones      = ["1", "2", "3"]
      spot       = false
    }
    spot = {
      vm_size        = "Standard_D4s_v5"
      node_count     = 0
      min_count      = 0
      max_count      = 10
      zones          = ["1", "2", "3"]
      spot           = true
      spot_max_price = -1
      node_taints    = ["kubernetes.azure.com/scalesetpriority=spot:NoSchedule"]
      node_labels    = { "workload" = "interruptible" }
    }
  }
}

variable "log_analytics_workspace_id" {
  description = "Log Analytics workspace ID for the Container Insights add-on and diagnostic settings."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
  default     = {}
}
