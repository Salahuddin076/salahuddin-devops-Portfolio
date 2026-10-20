variable "project_id" {
  description = "GCP project ID the required APIs are enabled on. Synthetic in this reference (never a real project)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must look like a GCP project ID (lowercase letters, digits, hyphens, 6-30 chars)."
  }
}

variable "services" {
  description = "Google APIs to enable on the project before any dependent resource (GKE, Cloud SQL, Secret Manager, Cloud Build, Artifact Registry, Container Scanning) can be created."
  type        = set(string)
  default = [
    "compute.googleapis.com",
    "container.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "containerscanning.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "iam.googleapis.com",
  ]
}

variable "disable_dependent_services_on_destroy" {
  description = "Whether disabling an API also disables services that depend on it. False here so a `terraform destroy` of this reference never cascades into a real project's other workloads."
  type        = bool
  default     = false
}
