variable "name" {
  description = "Node group name prefix, for example \"checkout\". The actual node group is named \"<name>-<architecture>\"."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}[a-z0-9]$", var.name))
    error_message = "name must be 3-32 characters of lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "cluster_name" {
  description = "Name of an existing EKS cluster. This module doesn't create one (see projects/aws-multi-region-eks-dr for a full cluster stack); it adds one architecture-specific managed node group to a cluster that already exists."
  type        = string

  validation {
    condition     = can(regex("^[0-9A-Za-z][A-Za-z0-9_-]{0,99}$", var.cluster_name))
    error_message = "cluster_name must be a valid EKS cluster name (1-100 characters, alphanumerics, hyphens and underscores)."
  }
}

variable "architecture" {
  description = "CPU architecture for this pool. This is the one variable that turns an x86 pool into a Graviton pool: it drives ami_type and the default instance family. Workload scheduling onto the pool is a separate, Kubernetes-side decision (see helm/multiarch-app) so capacity can exist on both architectures before any workload moves."
  type        = string

  validation {
    condition     = contains(["amd64", "arm64"], var.architecture)
    error_message = "architecture must be \"amd64\" or \"arm64\"."
  }
}

variable "subnet_ids" {
  description = "Subnet IDs for the node group (usually private subnets of the existing cluster's VPC)."
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) > 0
    error_message = "subnet_ids must not be empty."
  }
}

variable "instance_types" {
  description = "Instance types for the node group. null picks an architecture-appropriate default (m6i/c6i for amd64, m7g/c7g for arm64) so the common case needs no per-architecture tuning."
  type        = list(string)
  default     = null
}

variable "capacity_type" {
  description = "ON_DEMAND or SPOT. Graviton + Spot is a common pairing once the migration is validated (see docs/cost.md); default ON_DEMAND is the safer starting point for a pool still under compatibility testing."
  type        = string
  default     = "ON_DEMAND"

  validation {
    condition     = contains(["ON_DEMAND", "SPOT"], var.capacity_type)
    error_message = "capacity_type must be ON_DEMAND or SPOT."
  }
}

variable "scaling_config" {
  description = "Node group scaling bounds."
  type = object({
    min_size     = number
    desired_size = number
    max_size     = number
  })
  default = {
    min_size     = 1
    desired_size = 2
    max_size     = 4
  }

  validation {
    condition     = var.scaling_config.min_size >= 0 && var.scaling_config.desired_size >= var.scaling_config.min_size && var.scaling_config.max_size >= var.scaling_config.desired_size
    error_message = "scaling_config must satisfy min_size <= desired_size <= max_size, with min_size >= 0."
  }
}

variable "extra_labels" {
  description = "Extra Kubernetes node labels, merged with the architecture label this module always sets. Keep scheduling keyed off kubernetes.io/arch (EKS sets it natively from the AMI, independent of Terraform) so a rollback never depends on a custom label being correct."
  type        = map(string)
  default     = {}
}

variable "taint" {
  description = "Optional single taint while a pool is still under compatibility testing, for example {key = \"workload-pool\", value = \"canary\", effect = \"NO_SCHEDULE\"}. null applies no taint, which is the steady-state: scheduling is controlled entirely by nodeSelector/affinity on the Deployment side, so removing the ARM64 affinity is the whole rollback and nothing on the node side has to change."
  type = object({
    key    = string
    value  = string
    effect = string
  })
  default = null

  validation {
    condition     = var.taint == null || contains(["NO_SCHEDULE", "NO_EXECUTE", "PREFER_NO_SCHEDULE"], var.taint.effect)
    error_message = "taint.effect must be NO_SCHEDULE, NO_EXECUTE or PREFER_NO_SCHEDULE."
  }
}

variable "node_role_arn" {
  description = "Existing IAM role ARN for the node group. null makes this module create one with the standard worker policies."
  type        = string
  default     = null

  validation {
    condition     = var.node_role_arn == null || can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+$", var.node_role_arn))
    error_message = "node_role_arn must be an IAM role ARN, or null."
  }
}

variable "ecr_repository_arns" {
  description = "ECR repository ARNs this node group's instance profile may pull from, in addition to the account-wide AmazonEC2ContainerRegistryReadOnly policy. Usually left empty; present for accounts that scope ECR access per repository instead of the managed policy."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Extra tags for every resource this module creates (on top of the provider's default_tags)."
  type        = map(string)
  default     = {}
}
