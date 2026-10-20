variable "project_id" {
  description = "GCP project ID the cluster is created in. Synthetic in this reference."
  type        = string
}

variable "region" {
  description = "Region for a regional (multi-zone control plane) cluster. A zonal `location` is deliberately not supported: the whole point of this module is control-plane HA."
  type        = string
}

variable "cluster_name" {
  description = "Name of the GKE cluster."
  type        = string
  default     = "pharmacy-gke"
}

variable "network_id" {
  description = "Self-link / ID of the VPC the cluster's nodes attach to (module.network.network_id)."
  type        = string
}

variable "subnetwork_id" {
  description = "Self-link / ID of the subnet the cluster's nodes attach to (module.network.subnetwork_id)."
  type        = string
}

variable "pods_range_name" {
  description = "Secondary range name for pod IPs (module.network.pods_range_name)."
  type        = string
}

variable "services_range_name" {
  description = "Secondary range name for Service IPs (module.network.services_range_name)."
  type        = string
}

variable "master_ipv4_cidr_block" {
  description = "/28 CIDR for the GKE control plane's private endpoint. Must not overlap the subnet, pod or service ranges."
  type        = string
  default     = "172.16.0.0/28"

  validation {
    condition     = can(cidrhost(var.master_ipv4_cidr_block, 0)) && tonumber(split("/", var.master_ipv4_cidr_block)[1]) == 28
    error_message = "master_ipv4_cidr_block must be a /28 CIDR, as required by GKE private clusters."
  }
}

variable "enable_private_endpoint" {
  description = "If true, the control plane has no public IP at all and is reachable only from inside the VPC (or over a configured peering/VPN). False keeps a public endpoint restricted to master_authorized_networks, which is what this reference uses so `terraform validate`/docs examples don't imply a bastion is mandatory."
  type        = bool
  default     = false
}

variable "master_authorized_networks" {
  description = "CIDR blocks allowed to reach the public control-plane endpoint when enable_private_endpoint is false. Keep this to known operator/CI ranges, never 0.0.0.0/0."
  type = list(object({
    cidr_block   = string
    display_name = string
  }))
  default = [
    {
      cidr_block   = "203.0.113.0/24"
      display_name = "ci-runners"
    },
  ]
}

variable "release_channel" {
  description = "GKE release channel. REGULAR balances feature lag against unpatched-CVE exposure; RAPID/STABLE are also valid for different risk appetites."
  type        = string
  default     = "REGULAR"

  validation {
    condition     = contains(["RAPID", "REGULAR", "STABLE"], var.release_channel)
    error_message = "release_channel must be RAPID, REGULAR or STABLE."
  }
}

variable "node_pools" {
  description = <<-EOT
    One entry per node pool. The reference wiring (terraform/examples/reference)
    defines exactly two: an "api" pool for the Java services and an "ai" pool
    for inference workers, so a GPU-hungry batch of inference requests can
    never starve the API's CPU/memory or its own autoscaling budget. ai-shaped
    pools typically set min_count = 0 so the pool scales to zero outside
    working hours; api-shaped pools keep min_count >= 1 for latency-sensitive
    traffic.
  EOT
  type = map(object({
    machine_type = string
    min_count    = number
    max_count    = number
    disk_size_gb = number
    spot         = bool
    workload     = string # free-text label value, e.g. "api" or "ai-inference"
    taint = optional(object({
      key    = string
      value  = string
      effect = string
    }))
  }))

  validation {
    condition     = alltrue([for p in values(var.node_pools) : p.min_count >= 0 && p.max_count >= p.min_count])
    error_message = "every node pool needs 0 <= min_count <= max_count."
  }
}

variable "workload_identity_bindings" {
  description = <<-EOT
    Workload Identity bindings: which Kubernetes ServiceAccount (namespace/name)
    may impersonate which Google service account. This is the whole point of
    Workload Identity -- no google_service_account_key is ever created, so
    there is no JSON key file to leak, rotate or scan for in a pod image.
  EOT
  type = map(object({
    namespace                    = string
    ksa_name                     = string
    google_service_account_email = string
  }))
  default = {}
}

variable "resource_labels" {
  description = "Labels applied to the cluster resource."
  type        = map(string)
  default = {
    project = "gcp-ai-pharmacy-platform"
  }
}
