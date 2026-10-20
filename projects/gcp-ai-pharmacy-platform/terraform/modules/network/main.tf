# Custom-mode VPC: no auto-created subnets, one explicit regional subnet with
# Private Google Access so private GKE nodes reach Google APIs (Cloud SQL
# Admin, Secret Manager, Artifact Registry, Logging, Monitoring) without a
# public IP or a NAT hop.
resource "google_compute_network" "this" {
  project                 = var.project_id
  name                    = var.network_name
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "primary" {
  project       = var.project_id
  name          = "${var.network_name}-${var.region}"
  region        = var.region
  network       = google_compute_network.this.id
  ip_cidr_range = var.subnet_cidr

  # Lets nodes without an external IP reach *.googleapis.com directly.
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = var.pods_cidr
  }

  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = var.services_cidr
  }

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# Reserved internal range + peering connection so Cloud SQL (a Google-managed
# tenant project) can present a private IP inside this VPC instead of a
# public one.
resource "google_compute_global_address" "private_service_access" {
  project       = var.project_id
  name          = "${var.network_name}-psa"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.private_service_access_prefix_length
  network       = google_compute_network.this.id
}

resource "google_service_networking_connection" "private_service_access" {
  network                 = google_compute_network.this.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_service_access.name]
}

# Cloud Router + Cloud NAT: not the private connectivity path (that's Private
# Google Access above), just a logged, metered fallback for outbound traffic
# that isn't a Google API call, e.g. pulling a public base image. Disable it
# entirely once every image and dependency is mirrored through Artifact
# Registry and the AI pool's egress is fully private.
resource "google_compute_router" "this" {
  count   = var.enable_cloud_nat ? 1 : 0
  project = var.project_id
  name    = "${var.network_name}-router"
  region  = var.region
  network = google_compute_network.this.id
}

resource "google_compute_router_nat" "this" {
  count                              = var.enable_cloud_nat ? 1 : 0
  project                            = var.project_id
  name                               = "${var.network_name}-nat"
  router                             = google_compute_router.this[0].name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
