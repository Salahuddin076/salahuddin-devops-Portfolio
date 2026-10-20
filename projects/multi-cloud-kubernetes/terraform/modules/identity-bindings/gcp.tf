# GKE Workload Identity: one Google service account, bound to exactly one
# Kubernetes ServiceAccount (namespace/name) in the project's fixed workload
# identity pool (PROJECT_ID.svc.id.goog). No google_service_account_key is
# ever created, so there is no JSON key file to leak, rotate or scan for in
# a pod image. Same pattern as gcp-ai-pharmacy-platform's gke-cluster module,
# narrowed to the one portable ServiceAccount this project cares about.

resource "google_service_account" "portable_service" {
  project      = var.gcp_project_id
  account_id   = "portable-service"
  display_name = "portable-service workload identity"
}

resource "google_service_account_iam_member" "portable_service_workload_identity" {
  service_account_id = google_service_account.portable_service.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.gcp_project_id}.svc.id.goog[${var.service_account_namespace}/${var.service_account_name}]"
}
