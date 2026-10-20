output "repository_id" {
  description = "Artifact Registry repository ID."
  value       = google_artifact_registry_repository.images.repository_id
}

output "repository_url" {
  description = "Repository URL docker/other clients push to."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "cloudbuild_trigger_id" {
  description = "ID of the Cloud Build trigger."
  value       = google_cloudbuild_trigger.build_and_push.trigger_id
}
