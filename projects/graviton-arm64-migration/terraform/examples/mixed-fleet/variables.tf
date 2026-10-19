variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment tag."
  type        = string
  default     = "dev"
}

variable "cluster_name" {
  description = "Name of an existing EKS cluster to attach the node groups to."
  type        = string
  default     = "example-cluster"
}

variable "subnet_ids" {
  description = "Private subnet IDs of the existing cluster's VPC."
  type        = list(string)
  default     = ["subnet-0aaaaaaaaaaaaaaaa", "subnet-0bbbbbbbbbbbbbbbb"]
}

variable "node_pools" {
  description = "One entry per node pool. This is the toggle: changing an entry's architecture (or adding/removing entries) is the entire Terraform side of a staged migration. Scheduling workloads onto a pool is handled separately in helm/multiarch-app."
  type = map(object({
    architecture = string
    scaling_config = object({
      min_size     = number
      desired_size = number
      max_size     = number
    })
    capacity_type = optional(string, "ON_DEMAND")
  }))

  default = {
    # The pool every workload starts on.
    x86-stable = {
      architecture   = "amd64"
      scaling_config = { min_size = 2, desired_size = 3, max_size = 6 }
    }
    # Capacity for the migration. Starts small; the rollout plan
    # (docs/operations.md) grows it as services pass compatibility testing.
    # Deleting this block (or setting its desired_size to 0) is the
    # infrastructure-side rollback; the scheduling-side rollback in
    # helm/multiarch-app is independent and faster.
    graviton-migration = {
      architecture   = "arm64"
      scaling_config = { min_size = 1, desired_size = 2, max_size = 6 }
      capacity_type  = "SPOT"
    }
  }
}

variable "ecr_repository_name" {
  description = "Name of the shared multi-arch ECR repository."
  type        = string
  default     = "example/checkout-api"
}
