# The application password is generated here, never typed into a .tfvars
# file or committed anywhere; the caller is expected to write it straight
# into Secret Manager (see terraform/examples/reference/main.tf) and the
# Java service reads it back through the Secret Manager CSI/Workload Identity
# path, not through this module's state in plaintext logs.
resource "random_password" "app_user" {
  length  = 32
  special = true
}

resource "google_sql_database_instance" "this" {
  project          = var.project_id
  name             = var.instance_name
  region           = var.region
  database_version = var.database_version

  # No public IP is ever created for this instance, so there is nothing to
  # authorize in ip_configuration.authorized_networks.
  deletion_protection = var.deletion_protection

  depends_on = [var.private_vpc_connection]

  settings {
    tier              = var.tier
    availability_type = var.availability_type

    ip_configuration {
      ipv4_enabled    = false
      private_network = var.network_id
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      start_time                     = var.backup_start_time
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = var.transaction_log_retention_days

      backup_retention_settings {
        retained_backups = 30
        retention_unit   = "COUNT"
      }
    }

    insights_config {
      query_insights_enabled  = true
      record_application_tags = true
      record_client_address   = false
    }

    # pgaudit-style logging: these two flags, combined with the
    # google_project_iam_audit_config DATA_READ/DATA_WRITE entries in
    # modules/delivery, are what makes "who touched which row" answerable
    # after the fact instead of only "who connected".
    database_flags {
      name  = "log_connections"
      value = "on"
    }

    database_flags {
      name  = "log_disconnections"
      value = "on"
    }

    maintenance_window {
      day          = 7 # Sunday
      hour         = 4
      update_track = "stable"
    }
  }
}

resource "google_sql_database" "app" {
  project  = var.project_id
  name     = var.database_name
  instance = google_sql_database_instance.this.name
}

resource "google_sql_user" "app" {
  project  = var.project_id
  name     = var.database_user
  instance = google_sql_database_instance.this.name
  password = random_password.app_user.result
}
