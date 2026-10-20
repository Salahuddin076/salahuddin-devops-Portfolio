output "enabled_services" {
  description = "The set of API service names this module enabled."
  value       = [for s in google_project_service.this : s.service]
}

output "service_resources" {
  description = "The google_project_service resources, keyed by API name, so other modules can depend_on them explicitly."
  value       = google_project_service.this
}
