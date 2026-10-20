locals {
  # One (secret, accessor) pair per IAM binding, so adding an accessor to an
  # existing secret is a one-line diff instead of a full map replacement.
  secret_accessor_pairs = merge([
    for secret_key, secret in var.secrets : {
      for email in secret.accessor_emails :
      "${secret_key}:${email}" => {
        secret_key = secret_key
        email      = email
      }
    }
  ]...)
}

resource "google_secret_manager_secret" "this" {
  for_each = var.secrets

  project   = var.project_id
  secret_id = each.key
  labels    = each.value.labels

  replication {
    user_managed {
      dynamic "replicas" {
        for_each = var.replica_locations
        content {
          location = replicas.value
        }
      }
    }
  }
}

# Initial version. In a real deployment this is written out-of-band (by a
# rotation job or by Cloud SQL's module output) rather than committed to
# state as plaintext in var.secrets; this reference inlines a synthetic
# placeholder only so `terraform validate`/`plan` have a concrete value.
resource "google_secret_manager_secret_version" "initial" {
  for_each = var.secrets

  secret      = google_secret_manager_secret.this[each.key].id
  secret_data = each.value.secret_data
}

resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = local.secret_accessor_pairs

  project   = var.project_id
  secret_id = google_secret_manager_secret.this[each.value.secret_key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.email}"
}
