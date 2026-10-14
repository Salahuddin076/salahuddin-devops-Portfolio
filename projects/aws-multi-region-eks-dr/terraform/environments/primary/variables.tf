variable "region" {
  description = "AWS region for this stack (primary)."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.region))
    error_message = "region must be an AWS region name such as us-east-1."
  }
}

variable "app_name" {
  description = "Application name; the stack name is <app_name>-<region>."
  type        = string
  default     = "dr-app"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,7}$", var.app_name))
    error_message = "app_name must be 3-8 lowercase characters (it prefixes every name, some of which are length-limited)."
  }
}

variable "owner" {
  description = "Owner tag value."
  type        = string
  default     = "platform-team"
}

variable "vpc_cidr" {
  description = "VPC CIDR. Must not overlap the other region's VPC."
  type        = string
  default     = "10.10.0.0/16"
}

variable "nat_gateway_per_az" {
  description = "One NAT gateway per AZ (true) or a single shared one (false)."
  type        = bool
  default     = true
}

variable "kubernetes_version" {
  description = "EKS version; keep identical in both regions."
  type        = string
  default     = "1.34"
}

variable "endpoint_public_access_cidrs" {
  description = "CIDRs allowed to the public EKS endpoint (empty = private only)."
  type        = list(string)
  default     = []
}

variable "node_instance_types" {
  description = "Managed node group instance types."
  type        = list(string)
  default     = ["m7g.large"]
}

variable "node_scaling" {
  description = "Managed node group min/desired/max."
  type = object({
    min     = number
    desired = number
    max     = number
  })
  default = { min = 3, desired = 3, max = 12 }
}

variable "cluster_admin_principal_arns" {
  description = "IAM roles granted cluster admin via EKS access entries."
  type        = list(string)
  default     = []
}

variable "app_bucket_name" {
  description = "This region's application bucket (created by environments/global)."
  type        = string
  default     = "example-dr-app-data-us-east-1"
}

variable "app_secret_name" {
  description = "Database secret name (primary secret and DR replica share it)."
  type        = string
  default     = "dr-app/aurora-master"
}

variable "cache_node_type" {
  description = "Valkey node type."
  type        = string
  default     = "cache.t4g.small"
}

variable "cache_nodes" {
  description = "Valkey nodes in this region."
  type        = number
  default     = 2
}
