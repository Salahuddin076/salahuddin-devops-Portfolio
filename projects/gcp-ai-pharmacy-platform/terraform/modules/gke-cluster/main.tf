# Regional (multi-zone control plane), VPC-native, private-nodes GKE cluster.
# The default node pool is removed immediately: all actual capacity comes
# from the explicit api/ai pools below, so nothing ever schedules onto an
# unmanaged, untainted pool by accident.
resource "google_container_cluster" "this" {
  project  = var.project_id
  name     = var.cluster_name
  location = var.region

  remove_default_node_pool = true
  initial_node_count       = 1

  networking_mode = "VPC_NATIVE"
  network         = var.network_id
  subnetwork      = var.subnetwork_id

  ip_allocation_policy {
    cluster_secondary_range_name  = var.pods_range_name
    services_secondary_range_name = var.services_range_name
  }

  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = var.enable_private_endpoint
    master_ipv4_cidr_block  = var.master_ipv4_cidr_block
  }

  dynamic "master_authorized_networks_config" {
    for_each = var.enable_private_endpoint ? [] : [1]
    content {
      dynamic "cidr_blocks" {
        for_each = var.master_authorized_networks
        content {
          cidr_block   = cidr_blocks.value.cidr_block
          display_name = cidr_blocks.value.display_name
        }
      }
    }
  }

  # Workload Identity: pods authenticate as a Google service account by
  # impersonation (via the metadata server), never by mounting a downloaded
  # JSON key. See google_service_account_iam_member.workload_identity below
  # for the per-KSA bindings.
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  release_channel {
    channel = var.release_channel
  }

  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
  }

  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS", "STORAGE", "POD", "DEPLOYMENT"]
    managed_prometheus {
      enabled = true
    }
  }

  # Portfolio reference, never deployed: deletion protection would just be
  # one more manual step before anyone could tear this down after reviewing
  # it. A real production cluster should set this true.
  deletion_protection = false

  resource_labels = var.resource_labels
}

# Separate pools so an inference burst (AI pool) competes for nodes only with
# itself, never with the Java API pool's latency-sensitive capacity.
resource "google_container_node_pool" "this" {
  for_each = var.node_pools

  project  = var.project_id
  name     = each.key
  cluster  = google_container_cluster.this.name
  location = var.region

  autoscaling {
    min_node_count = each.value.min_count
    max_node_count = each.value.max_count
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type = each.value.machine_type
    disk_size_gb = each.value.disk_size_gb
    disk_type    = "pd-balanced"
    spot         = each.value.spot

    # GKE_METADATA is what actually lets a pod on this node use Workload
    # Identity; without it the legacy node-level metadata server is exposed
    # and impersonation bindings have nothing to hook into.
    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    labels = {
      "workload-pool" = each.value.workload
    }

    dynamic "taint" {
      for_each = each.value.taint != null ? [each.value.taint] : []
      content {
        key    = taint.value.key
        value  = taint.value.value
        effect = taint.value.effect
      }
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
  }
}

# Workload Identity bindings: one IAM policy member per Kubernetes
# ServiceAccount that needs to impersonate a Google service account. No
# google_service_account_key resource exists anywhere in this project.
resource "google_service_account_iam_member" "workload_identity" {
  for_each = var.workload_identity_bindings

  service_account_id = "projects/${var.project_id}/serviceAccounts/${each.value.google_service_account_email}"
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${each.value.namespace}/${each.value.ksa_name}]"
}
