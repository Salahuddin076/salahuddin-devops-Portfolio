variable "project_id" {
  description = "GCP project ID the secrets are created in. Synthetic in this reference."
  type        = string
}

variable "replica_locations" {
  description = "Regions Secret Manager replicates secret material to (user-managed replication). Scope this to where the service actually runs."
  type        = list(string)
}

variable "secrets" {
  description = <<-EOT
    One entry per logical secret, keyed by a short name (e.g. "db-credentials",
    "ai-model-api-key"). secret_data is the initial version's plaintext value;
    in this reference it is always a synthetic placeholder, never a real
    credential. accessor_emails lists the Google service accounts (normally
    the ones behind a Workload Identity binding) granted
    roles/secretmanager.secretAccessor on that one secret, and nothing else --
    least privilege is per secret, not project-wide.
  EOT
  type = map(object({
    secret_data     = string
    accessor_emails = list(string)
    labels          = optional(map(string), {})
  }))
}
