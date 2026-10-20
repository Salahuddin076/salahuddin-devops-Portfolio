# Reference wiring of all five modules into one example root so
# `terraform validate` can exercise the whole graph at once. In a real
# deployment each module below gets its own state/backend (network, cluster,
# database, secrets, delivery) so, e.g., a cluster upgrade can never touch
# the database's state file -- see docs/architecture.md and
# docs/decisions/0002-separate-state-per-layer.md.

module "apis" {
  source = "../../modules/project-apis"

  project_id = var.project_id
}

module "network" {
  source = "../../modules/network"

  project_id = var.project_id
  region     = var.region

  depends_on = [module.apis]
}

resource "google_service_account" "pharmacy_api" {
  project      = var.project_id
  account_id   = "pharmacy-api"
  display_name = "Pharmacy API workload (Workload Identity)"

  depends_on = [module.apis]
}

resource "google_service_account" "pharmacy_ai" {
  project      = var.project_id
  account_id   = "pharmacy-ai"
  display_name = "Pharmacy AI inference workload (Workload Identity)"

  depends_on = [module.apis]
}

module "gke" {
  source = "../../modules/gke-cluster"

  project_id          = var.project_id
  region              = var.region
  network_id          = module.network.network_id
  subnetwork_id       = module.network.subnetwork_id
  pods_range_name     = module.network.pods_range_name
  services_range_name = module.network.services_range_name

  node_pools = {
    api = {
      machine_type = "e2-standard-4"
      min_count    = 2
      max_count    = 6
      disk_size_gb = 50
      spot         = false
      workload     = "api"
    }
    ai = {
      machine_type = "n2-highmem-8"
      # Scales to zero outside working hours: inference traffic is bursty
      # and batch-shaped, so an idle AI pool costs nothing overnight.
      min_count    = 0
      max_count    = 10
      disk_size_gb = 100
      spot         = true
      workload     = "ai-inference"
      taint = {
        key    = "workload"
        value  = "ai-inference"
        effect = "NO_SCHEDULE"
      }
    }
  }

  workload_identity_bindings = {
    api = {
      namespace                    = "pharmacy"
      ksa_name                     = "pharmacy-api"
      google_service_account_email = google_service_account.pharmacy_api.email
    }
    ai = {
      namespace                    = "pharmacy"
      ksa_name                     = "pharmacy-ai"
      google_service_account_email = google_service_account.pharmacy_ai.email
    }
  }
}

module "cloud_sql" {
  source = "../../modules/cloud-sql"

  project_id             = var.project_id
  region                 = var.region
  network_id             = module.network.network_id
  private_vpc_connection = module.network.private_vpc_connection
}

module "secrets" {
  source = "../../modules/secret-manager"

  project_id        = var.project_id
  replica_locations = [var.region]

  secrets = {
    db-credentials = {
      secret_data = jsonencode({
        username = module.cloud_sql.database_user
        password = module.cloud_sql.database_password
        host     = module.cloud_sql.private_ip_address
        database = module.cloud_sql.database_name
      })
      accessor_emails = [google_service_account.pharmacy_api.email]
    }
    ai-model-api-key = {
      # Synthetic placeholder: a real deployment writes this out-of-band
      # (e.g. from a secrets-rotation pipeline), never commits it here.
      secret_data     = "CHANGE_ME_SYNTHETIC_PLACEHOLDER"
      accessor_emails = [google_service_account.pharmacy_ai.email]
    }
  }
}

module "delivery" {
  source = "../../modules/delivery"

  project_id = var.project_id
  region     = var.region
}
