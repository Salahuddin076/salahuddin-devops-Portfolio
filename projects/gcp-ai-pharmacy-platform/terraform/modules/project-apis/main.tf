# One resource per API so a single disabled-in-error API shows up on its own
# line in `terraform plan`/state, instead of one opaque for_each diff.
resource "google_project_service" "this" {
  for_each = var.services

  project                    = var.project_id
  service                    = each.value
  disable_dependent_services = var.disable_dependent_services_on_destroy
  disable_on_destroy         = false
}
