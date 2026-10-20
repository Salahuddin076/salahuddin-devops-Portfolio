variable "project_id" {
  description = "GCP project ID the network is created in. Synthetic in this reference."
  type        = string
}

variable "region" {
  description = "Region for the single primary subnet (the cluster and Cloud SQL instance live in the same region)."
  type        = string

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]$", var.region))
    error_message = "region must look like a GCP region, e.g. us-central1."
  }
}

variable "network_name" {
  description = "Name of the VPC network."
  type        = string
  default     = "pharmacy-vpc"
}

variable "subnet_cidr" {
  description = "Primary IPv4 CIDR for the GKE nodes and Cloud SQL private-IP peering range's consumer side."
  type        = string
  default     = "10.10.0.0/20"

  validation {
    condition     = can(cidrhost(var.subnet_cidr, 0))
    error_message = "subnet_cidr must be a valid IPv4 CIDR."
  }
}

variable "pods_cidr" {
  description = "Secondary range for GKE pod IPs (VPC-native / alias IP cluster)."
  type        = string
  default     = "10.20.0.0/14"

  validation {
    condition     = can(cidrhost(var.pods_cidr, 0))
    error_message = "pods_cidr must be a valid IPv4 CIDR."
  }
}

variable "services_cidr" {
  description = "Secondary range for GKE Service (ClusterIP) IPs."
  type        = string
  default     = "10.24.0.0/20"

  validation {
    condition     = can(cidrhost(var.services_cidr, 0))
    error_message = "services_cidr must be a valid IPv4 CIDR."
  }
}

variable "private_service_access_prefix_length" {
  description = "Prefix length of the reserved internal range used for VPC peering with Google-managed services (Cloud SQL private IP). /16 is Google's documented minimum recommendation for future headroom; this reference uses a smaller /20 by default to keep the example CIDR plan compact."
  type        = number
  default     = 20

  validation {
    condition     = var.private_service_access_prefix_length >= 16 && var.private_service_access_prefix_length <= 24
    error_message = "private_service_access_prefix_length must be between 16 and 24."
  }
}

variable "enable_cloud_nat" {
  description = "Whether to attach Cloud NAT to the subnet. Private GKE nodes reach Google APIs over Private Google Access without this; NAT is only for the rare case of pulling an image or package from outside Google's network, and is logged for audit."
  type        = bool
  default     = true
}
