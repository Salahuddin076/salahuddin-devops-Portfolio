# Artifact Registry with vulnerability scanning: scanning itself is a
# project-level feature of the Container Scanning / On-Demand Scanning API
# (enabled in modules/project-apis), triggered automatically on every push to
# a Docker repository once that API is on -- there is no separate
# "scan config" resource to create here. Immutable tags stop a scanned,
# approved image from being silently swapped for an unscanned one under the
# same tag.
resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_id
  format        = "DOCKER"
  description   = "Java API and AI inference images for the pharmacy platform."

  docker_config {
    immutable_tags = true
  }
}

# Cloud Build trigger: build-and-push on merge to main. The vulnerability
# scan runs on push to Artifact Registry above; a build-time gate (failing
# the pipeline on a HIGH/CRITICAL finding) is implemented as a step inside
# cloudbuild.yaml in the application repo, not as Terraform here, since that
# policy belongs to app-repo CI config, not infrastructure.
resource "google_cloudbuild_trigger" "build_and_push" {
  project     = var.project_id
  location    = var.region
  name        = "${var.repository_id}-build"
  description = "Build, scan and push on merge to ${var.trigger_branch_pattern}."
  filename    = var.cloudbuild_filename

  github {
    owner = var.repo_owner
    name  = var.repo_name
    push {
      branch = var.trigger_branch_pattern
    }
  }

  substitutions = {
    _ARTIFACT_REGISTRY_REPO = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repository_id}"
  }
}

# Data-access audit logs: who READ or WROTE which row/secret, not just who
# connected. ADMIN_READ covers metadata/config reads (e.g. listing secrets or
# instances). These are authoritative resources for the whole project's audit
# config for each service, so there is exactly one of each.
resource "google_project_iam_audit_config" "cloud_sql" {
  count   = var.enable_audit_logs ? 1 : 0
  project = var.project_id
  service = "cloudsql.googleapis.com"

  audit_log_config {
    log_type = "ADMIN_READ"
  }
  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
}

resource "google_project_iam_audit_config" "secret_manager" {
  count   = var.enable_audit_logs ? 1 : 0
  project = var.project_id
  service = "secretmanager.googleapis.com"

  audit_log_config {
    log_type = "ADMIN_READ"
  }
  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
}
