output "network_id" {
  description = "Self-link / ID of the VPC network."
  value       = google_compute_network.this.id
}

output "network_name" {
  description = "Name of the VPC network."
  value       = google_compute_network.this.name
}

output "subnetwork_id" {
  description = "Self-link / ID of the primary regional subnet."
  value       = google_compute_subnetwork.primary.id
}

output "subnetwork_name" {
  description = "Name of the primary regional subnet."
  value       = google_compute_subnetwork.primary.name
}

output "pods_range_name" {
  description = "Name of the secondary range used for pod IPs."
  value       = google_compute_subnetwork.primary.secondary_ip_range[0].range_name
}

output "services_range_name" {
  description = "Name of the secondary range used for Service IPs."
  value       = google_compute_subnetwork.primary.secondary_ip_range[1].range_name
}

output "private_vpc_connection" {
  description = "The servicenetworking peering connection. Cloud SQL must depend_on this so the private IP is assignable."
  value       = google_service_networking_connection.private_service_access
}
