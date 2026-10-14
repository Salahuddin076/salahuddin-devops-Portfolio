variable "name" {
  description = "Name prefix for every resource in this region (for example dr-app-use1)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,23}$", var.name))
    error_message = "name must be 3-24 characters: lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "role" {
  description = "This region's role at deploy time: primary or dr. Only sizing defaults and tags depend on it; failover does not change it."
  type        = string

  validation {
    condition     = contains(["primary", "dr"], var.role)
    error_message = "role must be primary or dr."
  }
}

# --- network -------------------------------------------------------------------

variable "vpc_cidr" {
  description = "VPC CIDR (RFC 1918, /16 to /20). Use non-overlapping ranges per region so the VPCs can be peered later."
  type        = string

  validation {
    condition = (
      can(cidrhost(var.vpc_cidr, 0)) &&
      tonumber(split("/", var.vpc_cidr)[1]) >= 16 &&
      tonumber(split("/", var.vpc_cidr)[1]) <= 20 &&
      can(regex("^(10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.)", var.vpc_cidr))
    )
    error_message = "vpc_cidr must be an RFC 1918 CIDR between /16 and /20."
  }
}

variable "az_count" {
  description = "Number of availability zones. Fixed at 3: the chart's topology spread and the Aurora/Valkey subnet groups assume three."
  type        = number
  default     = 3

  validation {
    condition     = var.az_count == 3
    error_message = "az_count must be 3."
  }
}

variable "nat_gateway_per_az" {
  description = "true: one NAT gateway per AZ (no cross-AZ dependency for egress). false: a single NAT gateway (cheaper; acceptable for a warm-standby region)."
  type        = bool
  default     = true
}

# --- EKS -----------------------------------------------------------------------

variable "kubernetes_version" {
  description = "EKS Kubernetes version (major.minor). Keep both regions on the same version; the chart is validated against it."
  type        = string
  default     = "1.34"

  validation {
    condition     = can(regex("^1\\.(3[3-9])$", var.kubernetes_version))
    error_message = "kubernetes_version must be 1.33 or newer, as major.minor (for example 1.34)."
  }
}

variable "endpoint_public_access_cidrs" {
  description = "CIDRs allowed to reach the public EKS API endpoint. Empty list = private endpoint only (needs VPN or a bastion)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for c in var.endpoint_public_access_cidrs : can(cidrhost(c, 0)) && c != "0.0.0.0/0"])
    error_message = "endpoint_public_access_cidrs must be valid CIDRs and must not include 0.0.0.0/0."
  }
}

variable "node_instance_types" {
  description = "Instance types for the managed node group (Graviton by default)."
  type        = list(string)
  default     = ["m7g.large"]

  validation {
    condition     = length(var.node_instance_types) > 0
    error_message = "node_instance_types must list at least one instance type."
  }
}

variable "node_ami_type" {
  description = "Managed node group AMI type. Must match the instance architecture."
  type        = string
  default     = "AL2023_ARM_64_STANDARD"

  validation {
    condition     = contains(["AL2023_ARM_64_STANDARD", "AL2023_x86_64_STANDARD", "BOTTLEROCKET_ARM_64", "BOTTLEROCKET_x86_64"], var.node_ami_type)
    error_message = "node_ami_type must be an AL2023 or Bottlerocket AMI type."
  }
}

variable "node_scaling" {
  description = "Managed node group size. DR runs small (min 2, desired 2) and is scaled up during failover; primary runs at production size."
  type = object({
    min     = number
    desired = number
    max     = number
  })

  validation {
    condition = (
      var.node_scaling.min >= 1 &&
      var.node_scaling.min <= var.node_scaling.desired &&
      var.node_scaling.desired <= var.node_scaling.max
    )
    error_message = "node_scaling must satisfy 1 <= min <= desired <= max."
  }
}

variable "cluster_admin_principal_arns" {
  description = "IAM role ARNs granted cluster admin through EKS access entries (no aws-auth ConfigMap)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for a in var.cluster_admin_principal_arns : can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:role/", a))])
    error_message = "cluster_admin_principal_arns must be IAM role ARNs."
  }
}

variable "cluster_log_types" {
  description = "EKS control plane log types sent to CloudWatch Logs."
  type        = list(string)
  default     = ["api", "audit", "authenticator"]

  validation {
    condition     = alltrue([for t in var.cluster_log_types : contains(["api", "audit", "authenticator", "controllerManager", "scheduler"], t)])
    error_message = "cluster_log_types may only contain api, audit, authenticator, controllerManager, scheduler."
  }
}

variable "log_retention_days" {
  description = "Retention for the EKS control plane log group."
  type        = number
  default     = 90

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be a value CloudWatch Logs accepts."
  }
}

# --- application wiring --------------------------------------------------------

variable "app_namespace" {
  description = "Kubernetes namespace of the order API (Pod Identity association)."
  type        = string
  default     = "orders"

  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", var.app_namespace))
    error_message = "app_namespace must be a valid Kubernetes namespace name."
  }
}

variable "app_service_account" {
  description = "Service account name the chart creates (Pod Identity association)."
  type        = string
  default     = "order-api"

  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", var.app_service_account))
    error_message = "app_service_account must be a valid Kubernetes name."
  }
}

variable "app_bucket_name" {
  description = "Name of this region's application bucket (created by the global-data module). The app role gets read/write on it."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.app_bucket_name))
    error_message = "app_bucket_name must be a valid S3 bucket name."
  }
}

variable "app_secret_name" {
  description = "Name of the database secret (created in the primary by global-data and replicated to DR under the same name)."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9/_+=.@-]{1,256}$", var.app_secret_name))
    error_message = "app_secret_name must be a valid Secrets Manager name."
  }
}

# --- Valkey --------------------------------------------------------------------

variable "cache_node_type" {
  description = "ElastiCache Valkey node type."
  type        = string
  default     = "cache.t4g.small"

  validation {
    condition     = can(regex("^cache\\.", var.cache_node_type))
    error_message = "cache_node_type must start with cache."
  }
}

variable "cache_nodes" {
  description = "Valkey nodes (1 primary + replicas). 2 or more enables Multi-AZ automatic failover inside the region."
  type        = number
  default     = 2

  validation {
    condition     = var.cache_nodes >= 1 && var.cache_nodes <= 6
    error_message = "cache_nodes must be between 1 and 6."
  }
}

variable "cache_engine_version" {
  description = "Valkey engine version."
  type        = string
  default     = "8.0"

  validation {
    condition     = can(regex("^[78]\\.[0-9]+$", var.cache_engine_version))
    error_message = "cache_engine_version must be a Valkey 7.x or 8.x version."
  }
}

# --- KMS -----------------------------------------------------------------------

variable "kms_deletion_window_days" {
  description = "Waiting period before the regional KMS key is deleted."
  type        = number
  default     = 30

  validation {
    condition     = var.kms_deletion_window_days >= 7 && var.kms_deletion_window_days <= 30
    error_message = "kms_deletion_window_days must be between 7 and 30."
  }
}

variable "tags" {
  description = "Extra tags for resources in this module (the provider's default_tags still apply)."
  type        = map(string)
  default     = {}
}
