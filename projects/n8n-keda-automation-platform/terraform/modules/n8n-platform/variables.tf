variable "name" {
  description = "Prefix for every resource name, e.g. n8n-prod."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.name))
    error_message = "name must be 2-31 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "cluster_name" {
  description = "Existing EKS cluster that runs n8n. Pod Identity associations are created on it."
  type        = string
}

variable "vpc_id" {
  description = "VPC of the cluster. RDS, ElastiCache and the security groups go here."
  type        = string
}

variable "data_subnet_ids" {
  description = "Private subnets (at least two AZs) for the RDS and ElastiCache subnet groups."
  type        = list(string)

  validation {
    condition     = length(var.data_subnet_ids) >= 2
    error_message = "data_subnet_ids needs at least two subnets in different AZs."
  }
}

variable "additional_client_security_group_ids" {
  description = "Extra security groups allowed to reach Postgres and Redis, e.g. the node security group when security groups for pods are not used. The n8n pod security group created here is always allowed."
  type        = list(string)
  default     = []
}

variable "namespace" {
  description = "Kubernetes namespace of the n8n release."
  type        = string
  default     = "n8n"
}

variable "service_account" {
  description = "ServiceAccount shared by n8n main, webhook and worker pods (chart value serviceAccount.name)."
  type        = string
  default     = "n8n"
}

variable "keda_namespace" {
  description = "Namespace KEDA is installed in."
  type        = string
  default     = "keda"
}

variable "keda_service_account" {
  description = "ServiceAccount of the KEDA operator, which reads the Redis AUTH token for the scaler."
  type        = string
  default     = "keda-operator"
}

# Secrets (containers only; values are put out of band).

variable "encryption_key_secret_name" {
  description = "Secrets Manager name of the n8n encryption key (plain string)."
  type        = string
  default     = "n8n/encryption-key"
}

variable "db_app_secret_name" {
  description = "Secrets Manager name of the n8n application DB role, JSON {username, password}."
  type        = string
  default     = "n8n/db-app-credentials"
}

variable "redis_auth_secret_name" {
  description = "Secrets Manager name of the ElastiCache AUTH token (plain string, 16-128 printable characters)."
  type        = string
  default     = "n8n/redis-auth"
}

variable "recovery_window_in_days" {
  description = "Days a deleted secret can be restored. Losing the encryption key loses every stored credential, so keep this long."
  type        = number
  default     = 30

  validation {
    condition     = var.recovery_window_in_days >= 7 && var.recovery_window_in_days <= 30
    error_message = "recovery_window_in_days must be 7-30 (0, immediate deletion, is not allowed here)."
  }
}

# ElastiCache (Valkey).

variable "cache_engine_version" {
  description = "Valkey engine version."
  type        = string
  default     = "8.0"
}

variable "cache_node_type" {
  description = "ElastiCache node type. The Bull queue holds job IDs and small payloads; it is small."
  type        = string
  default     = "cache.t4g.small"
}

variable "cache_multi_az" {
  description = "Two nodes in different AZs with automatic failover. A lost queue loses only queued (not yet started) executions, but webhooks fail while Redis is down."
  type        = bool
  default     = true
}

variable "redis_auth_token_version" {
  description = "Bump to push a new AUTH token from Secrets Manager to ElastiCache (write-only argument; the token never enters state). See docs/operations.md for the two-step rotation."
  type        = number
  default     = 1
}

variable "redis_auth_token_update_strategy" {
  description = "How a new token is applied: ROTATE keeps the old one valid too (use while pods still hold it), SET then drops the old one."
  type        = string
  default     = "ROTATE"

  validation {
    condition     = contains(["ROTATE", "SET"], var.redis_auth_token_update_strategy)
    error_message = "redis_auth_token_update_strategy must be ROTATE or SET."
  }
}

variable "cache_snapshot_retention_days" {
  description = "Daily snapshots kept. Useful for forensics more than recovery: queued jobs are short-lived."
  type        = number
  default     = 1
}

# RDS PostgreSQL.

variable "db_engine_version" {
  description = "PostgreSQL major (or major.minor) version. Minor upgrades are automatic."
  type        = string
  default     = "16"
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "db_allocated_storage" {
  description = "Initial gp3 storage in GiB."
  type        = number
  default     = 50
}

variable "db_max_allocated_storage" {
  description = "Storage autoscaling ceiling in GiB. Execution data grows until pruning catches up."
  type        = number
  default     = 200
}

variable "db_multi_az" {
  description = "Synchronous standby in a second AZ."
  type        = bool
  default     = true
}

variable "db_backup_retention_days" {
  description = "Automated backup retention (point-in-time recovery window)."
  type        = number
  default     = 14

  validation {
    condition     = var.db_backup_retention_days >= 7 && var.db_backup_retention_days <= 35
    error_message = "db_backup_retention_days must be 7-35: n8n's workflows and credentials live only in this database."
  }
}

variable "db_deletion_protection" {
  description = "Block deleting the instance. Turn off only to tear down a test environment."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags added to every resource (on top of the provider's default_tags)."
  type        = map(string)
  default     = {}
}
