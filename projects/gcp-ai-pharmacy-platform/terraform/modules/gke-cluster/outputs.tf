output "cluster_name" {
  description = "Name of the GKE cluster."
  value       = google_container_cluster.this.name
}

output "cluster_endpoint" {
  description = "Control-plane endpoint IP (private or public, depending on enable_private_endpoint)."
  value       = google_container_cluster.this.endpoint
  sensitive   = true
}

output "cluster_ca_certificate" {
  description = "Base64-encoded cluster CA certificate."
  value       = google_container_cluster.this.master_auth[0].cluster_ca_certificate
  sensitive   = true
}

output "workload_identity_pool" {
  description = "The Workload Identity pool (<project>.svc.id.goog) pods impersonate into."
  value       = google_container_cluster.this.workload_identity_config[0].workload_pool
}

output "node_pool_names" {
  description = "Names of the node pools created, keyed the same as var.node_pools."
  value       = { for k, v in google_container_node_pool.this : k => v.name }
}
