output "cluster_name" {
  description = "Name of the GKE cluster."
  value       = module.gke.cluster_name
}

output "node_pool_names" {
  description = "Names of the api/ai node pools."
  value       = module.gke.node_pool_names
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL connection name."
  value       = module.cloud_sql.connection_name
}

output "artifact_registry_repository_url" {
  description = "Artifact Registry repository URL."
  value       = module.delivery.repository_url
}

output "secret_ids" {
  description = "Secret Manager secret IDs."
  value       = module.secrets.secret_ids
}
