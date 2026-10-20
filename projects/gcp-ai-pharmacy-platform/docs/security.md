# Security

## Identity: Workload Identity, never a key file

Every pod that needs to call a Google API (Secret Manager, Cloud SQL Admin, Cloud Logging, Cloud Monitoring) authenticates by impersonating a Google service account through the GKE metadata server. The binding has two sides that must both be correct:

1. **IAM side** (`terraform/modules/gke-cluster/main.tf`): `google_service_account_iam_member.workload_identity` grants `roles/iam.workloadIdentityUser` to the member `serviceAccount:<project>.svc.id.goog[<namespace>/<ksa_name>]`.
2. **Kubernetes side** (`helm/pharmacy-service/templates/serviceaccount.yaml`): the `ServiceAccount` carries the annotation `iam.gke.io/gcp-service-account: <the same GSA email>`.

If either side names a different namespace, KSA name, or GSA email than the other, impersonation fails at runtime with a 403 from the metadata server — not at `terraform validate` or `helm template` time. `tests/test_terraform_static.py` and `tests/test_helm_static.py` each assert the exact shape of their half independently, and `terraform/examples/reference/main.tf` is the one place both halves are wired from the same values (`google_service_account.pharmacy_api.email` etc.) so they can't drift apart in this reference.

No `google_service_account_key` resource exists anywhere in this project. `tests/test_terraform_static.py::test_no_service_account_keys_anywhere` enforces that as a standing invariant, not just a one-time check.

## Network: private by default

- GKE nodes: `enable_private_nodes = true`. No node ever has a public IP.
- GKE control plane: public by default in this reference (`enable_private_endpoint = false`), but restricted to `master_authorized_networks` — never `0.0.0.0/0` — and can be flipped fully private with one variable.
- Cloud SQL: `ipv4_enabled = false`. The instance has no public IP, so there's no public-IP firewall surface to misconfigure.
- Private Google Access (`private_ip_google_access = true` on the subnet) is what lets private nodes reach `*.googleapis.com` without a NAT hop or a public IP. Cloud NAT exists only as a logged fallback for genuinely external egress (e.g., pulling a public base image), and can be disabled entirely (`enable_cloud_nat = false`) once every dependency is mirrored into Artifact Registry.

## Secrets: per-secret, least-privilege access

`modules/secret-manager` grants `roles/secretmanager.secretAccessor` per secret to the specific service account that needs it (`accessor_emails` on each entry in `var.secrets`), not a blanket project-level grant. In the reference wiring, the `pharmacy-api` GSA can read `db-credentials` but not `ai-model-api-key`, and vice versa for `pharmacy-ai` — so a compromise of one workload's identity doesn't hand over the other's secrets.

## Auditability

`google_project_iam_audit_config` (in `modules/delivery`, since it's authoritative project-wide and must exist in exactly one place) turns on `ADMIN_READ`, `DATA_READ` and `DATA_WRITE` audit logging for both `cloudsql.googleapis.com` and `secretmanager.googleapis.com`. Combined with Cloud SQL's `log_connections`/`log_disconnections` database flags, this is what makes "who read which secret, and who queried which row, and when" answerable from Cloud Logging after the fact — not just "who connected to the instance."

## Supply chain

Artifact Registry's Docker repository sets `immutable_tags = true`: once a tag is pushed (and scanned), it cannot be silently overwritten with a different, unscanned image under the same tag. Vulnerability scanning itself is a project-level feature of the Container Scanning API (enabled in `modules/project-apis`) that runs automatically on push — there's no separate "scan config" resource. The build-time *gate* (fail the Cloud Build run if a HIGH/CRITICAL finding comes back) is implemented as a step in the application repository's `cloudbuild.yaml`, which lives outside this infrastructure repo.

## What this reference does not cover

- Cloud Armor rule content (rate limiting, WAF rules) at the load balancer — the architecture diagram shows where it sits, but no `google_compute_security_policy` resource is included; that belongs with the `cloud-security-waf` project's AWS WAF pattern conceptually, not duplicated here.
- KMS-based envelope encryption of Cloud SQL or Secret Manager data at rest beyond Google's default encryption — out of scope for this reference.
- Binary Authorization / admission control blocking unscanned images from being deployed — a natural next step, not built here.
