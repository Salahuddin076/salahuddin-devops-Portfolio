# 0001: Workload Identity over service-account key files

## Status

Accepted.

## Context

Pods on GKE need to call Google APIs (Secret Manager, Cloud SQL Admin surface, Cloud Logging, Cloud Monitoring). The two common ways to grant that: mount a downloaded `google_service_account_key` JSON file as a Kubernetes Secret and point `GOOGLE_APPLICATION_CREDENTIALS` at it, or use GKE Workload Identity so a pod's Kubernetes ServiceAccount impersonates a Google service account through the node's metadata server, with no key file ever created.

## Decision

Workload Identity. Every service account in this project is bound via `google_service_account_iam_member` with `roles/iam.workloadIdentityUser`, scoped to one `namespace/ServiceAccount` pair. No `google_service_account_key` resource exists anywhere in the Terraform.

## Consequences

- There is no JSON key to leak via a container image layer, a `kubectl describe secret`, a misconfigured RBAC rule, or a laptop. The identity lives entirely in GCP's control plane and the pod's bound token is short-lived.
- There's nothing to rotate on a schedule — impersonation tokens are minted per-request and expire on their own, removing an entire class of "someone forgot to rotate the key" incidents.
- The binding is two-sided (IAM member string + Kubernetes annotation) and both sides must name the same namespace/KSA/GSA triple. Getting this wrong fails at pod runtime with an opaque 403 from the metadata server, not at `terraform validate` or `helm template` time — see `docs/security.md` for how this reference tests both sides independently to catch drift.
- Workload Identity requires `GKE_METADATA` mode on the node pool (`workload_metadata_config` in `modules/gke-cluster`); a node pool created without it silently falls back to the legacy metadata server and breaks impersonation for anything scheduled there.
