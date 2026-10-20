output "secret_ids" {
  description = "Secret Manager secret IDs, keyed the same as var.secrets."
  value       = { for k, v in google_secret_manager_secret.this : k => v.secret_id }
}

output "secret_full_names" {
  description = "Fully-qualified secret resource names (projects/.../secrets/...), keyed the same as var.secrets."
  value       = { for k, v in google_secret_manager_secret.this : k => v.id }
}
