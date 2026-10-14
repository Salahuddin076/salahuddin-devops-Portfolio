variable "name" {
  description = "Prefix for the IAM role, KMS alias and other names this module creates."
  type        = string
  default     = "secure-frontend"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,38}[a-z0-9]$", var.name))
    error_message = "name must be 3-40 characters of lowercase letters, digits and hyphens, starting with a letter."
  }
}

# --- existing cluster ------------------------------------------------------------

variable "cluster_name" {
  description = "Name of an existing EKS cluster. This module doesn't create one (see projects/aws-multi-region-eks-dr for a full cluster stack)."
  type        = string

  validation {
    condition     = can(regex("^[0-9A-Za-z][A-Za-z0-9_-]{0,99}$", var.cluster_name))
    error_message = "cluster_name must be a valid EKS cluster name (1-100 characters, alphanumerics, hyphens and underscores)."
  }
}

variable "manage_pod_identity_agent_addon" {
  description = "Install the eks-pod-identity-agent add-on here. Leave false when the cluster stack already manages it (the multi-region sibling does)."
  type        = bool
  default     = false
}

variable "pod_identity_agent_addon_version" {
  description = "Version of eks-pod-identity-agent when manage_pod_identity_agent_addon is true. null lets EKS pick the default for the cluster version."
  type        = string
  default     = null
}

# --- Secrets Store CSI Driver + ASCP (one EKS add-on) -----------------------------

variable "csi_addon_version" {
  description = "Version of the aws-secrets-store-csi-driver-provider add-on (it bundles the CSI driver and the AWS provider). Pin it per environment; null lets EKS pick the default."
  type        = string
  default     = null

  validation {
    condition     = var.csi_addon_version == null || can(regex("^v[0-9]+\\.[0-9]+\\.[0-9]+", var.csi_addon_version))
    error_message = "csi_addon_version must look like v1.2.3-eksbuild.1, or be null."
  }
}

variable "sync_secret_enabled" {
  description = "Driver-level syncSecret.enabled. Grants the driver RBAC to create and update Kubernetes Secrets so SecretProviderClass secretObjects work. Off by default: the app reads files, and a synced Secret puts the value in etcd."
  type        = bool
  default     = false
}

variable "enable_secret_rotation" {
  description = "Driver-level enableSecretRotation. When true the driver re-fetches mounted secrets every rotation_poll_interval and rewrites the files."
  type        = bool
  default     = true
}

variable "rotation_poll_interval" {
  description = "Driver-level rotationPollInterval (Go duration, e.g. 2m). Each poll is one GetSecretValue per mounted secret per pod; see docs/cost.md."
  type        = string
  default     = "2m"

  validation {
    condition = (
      can(regex("^[0-9]+(s|m|h)$", var.rotation_poll_interval)) &&
      try(tonumber(regex("^[0-9]+", var.rotation_poll_interval)) * lookup({ s = 1, m = 60, h = 3600 }, regex("[smh]$", var.rotation_poll_interval), 0) >= 30, false)
    )
    error_message = "rotation_poll_interval must be a whole number of s, m or h, and at least 30s (polling faster mostly buys API calls)."
  }
}

# --- secrets ---------------------------------------------------------------------

variable "db_secret_name" {
  description = "Name of the DB credential secret. Its value is JSON {\"username\", \"password\", \"host\"}, set out of band; Terraform never sees it."
  type        = string
  default     = "secure-frontend/db-credentials"

  validation {
    condition     = can(regex("^[A-Za-z0-9/_+=.@-]{1,512}$", var.db_secret_name))
    error_message = "db_secret_name may contain only letters, digits and /_+=.@- (Secrets Manager naming rules)."
  }
}

variable "api_key_secret_name" {
  description = "Name of the API key secret (plain string value, set out of band)."
  type        = string
  default     = "secure-frontend/api-key"

  validation {
    condition     = can(regex("^[A-Za-z0-9/_+=.@-]{1,512}$", var.api_key_secret_name))
    error_message = "api_key_secret_name may contain only letters, digits and /_+=.@- (Secrets Manager naming rules)."
  }
}

variable "recovery_window_in_days" {
  description = "Days a deleted secret stays recoverable. 0 deletes immediately (lab use only)."
  type        = number
  default     = 30

  validation {
    condition     = var.recovery_window_in_days == 0 || (var.recovery_window_in_days >= 7 && var.recovery_window_in_days <= 30)
    error_message = "recovery_window_in_days must be 0 or between 7 and 30."
  }
}

variable "rotation_lambda_arn" {
  description = "ARN of an existing rotation Lambda for the DB secret (for example the AWS-provided single-user PostgreSQL rotation function). null disables rotation. Set it only after the first value exists."
  type        = string
  default     = null

  validation {
    condition     = var.rotation_lambda_arn == null || can(regex("^arn:aws[a-z-]*:lambda:[a-z0-9-]+:[0-9]{12}:function:[A-Za-z0-9_-]+(:[A-Za-z0-9_$-]+)?$", var.rotation_lambda_arn))
    error_message = "rotation_lambda_arn must be a Lambda function ARN, or null."
  }
}

variable "rotation_days" {
  description = "Days between automatic rotations of the DB secret when rotation_lambda_arn is set."
  type        = number
  default     = 30

  validation {
    condition     = var.rotation_days >= 1 && var.rotation_days <= 365 && floor(var.rotation_days) == var.rotation_days
    error_message = "rotation_days must be a whole number between 1 and 365."
  }
}

variable "kms_deletion_window_in_days" {
  description = "Waiting period before the CMK is deleted."
  type        = number
  default     = 30

  validation {
    condition     = var.kms_deletion_window_in_days >= 7 && var.kms_deletion_window_in_days <= 30
    error_message = "kms_deletion_window_in_days must be between 7 and 30."
  }
}

# --- workload identity -----------------------------------------------------------

variable "namespace" {
  description = "Kubernetes namespace of the app. Must match the Helm release namespace."
  type        = string
  default     = "web"

  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.namespace)) && length(var.namespace) <= 63
    error_message = "namespace must be a valid Kubernetes namespace name."
  }
}

variable "service_account" {
  description = "Kubernetes ServiceAccount of the app. Must match the chart's serviceAccount.name."
  type        = string
  default     = "secure-frontend"

  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.service_account)) && length(var.service_account) <= 63
    error_message = "service_account must be a valid Kubernetes name."
  }
}

variable "tags" {
  description = "Extra tags for every resource (on top of the provider's default_tags)."
  type        = map(string)
  default     = {}
}
