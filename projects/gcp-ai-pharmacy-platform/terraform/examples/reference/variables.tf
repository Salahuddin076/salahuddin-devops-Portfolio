variable "project_id" {
  description = "GCP project ID. Synthetic placeholder in this reference -- never a real project."
  type        = string
  default     = "example-pharmacy-platform"
}

variable "region" {
  description = "Region for every regional resource (subnet, GKE cluster, Cloud SQL, Artifact Registry, Cloud Build trigger)."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment label applied to resources."
  type        = string
  default     = "reference"
}
