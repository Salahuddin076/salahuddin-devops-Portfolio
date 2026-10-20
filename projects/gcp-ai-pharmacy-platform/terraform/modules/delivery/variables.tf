variable "project_id" {
  description = "GCP project ID. Synthetic in this reference."
  type        = string
}

variable "region" {
  description = "Region for the Artifact Registry repository and Cloud Build trigger."
  type        = string
}

variable "repository_id" {
  description = "Artifact Registry Docker repository name."
  type        = string
  default     = "pharmacy-images"
}

variable "repo_owner" {
  description = "Synthetic source-repo owner/org used to wire the Cloud Build trigger example. Never a real account."
  type        = string
  default     = "example-org"
}

variable "repo_name" {
  description = "Synthetic source-repo name used to wire the Cloud Build trigger example."
  type        = string
  default     = "pharmacy-platform"
}

variable "trigger_branch_pattern" {
  description = "Branch regex that fires the build (RE2 syntax, as used by Cloud Build)."
  type        = string
  default     = "^main$"
}

variable "cloudbuild_filename" {
  description = "Path to the Cloud Build config file inside the source repo."
  type        = string
  default     = "cloudbuild.yaml"
}

variable "enable_audit_logs" {
  description = "Enable DATA_READ/DATA_WRITE/ADMIN_READ audit log configs for Cloud SQL and Secret Manager at the project level. On by default: this is the auditable-access requirement the whole platform exists to satisfy."
  type        = bool
  default     = true
}
