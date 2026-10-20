output "instance_name" {
  description = "Name of the Cloud SQL instance."
  value       = google_sql_database_instance.this.name
}

output "connection_name" {
  description = "Cloud SQL connection name (project:region:instance), used by the Cloud SQL Auth Proxy / connector."
  value       = google_sql_database_instance.this.connection_name
}

output "private_ip_address" {
  description = "Private IPv4 address of the instance."
  value       = google_sql_database_instance.this.private_ip_address
}

output "database_name" {
  description = "Name of the application database."
  value       = google_sql_database.app.name
}

output "database_user" {
  description = "Name of the application database user."
  value       = google_sql_user.app.name
}

output "database_password" {
  description = "Generated application database password. Write this into Secret Manager; never into a tfvars file or log."
  value       = random_password.app_user.result
  sensitive   = true
}
