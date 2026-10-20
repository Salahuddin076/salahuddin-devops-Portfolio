# Security

- **No static cloud credentials in any pod.** Every ServiceAccount
  annotation in `helm/portable-service` is a workload-identity reference
  (an IAM role ARN, a managed identity client ID, a Google service account
  email) -- never an access key, client secret, or JSON key file.
  `tests/test_helm_static.py` asserts none of the forbidden credential
  shapes (`AKIA`, `client_secret`, `GOOGLE_APPLICATION_CREDENTIALS`,
  `.json` key references) ever appear in the chart.
- **IRSA on EKS** (`terraform/modules/identity-bindings/aws.tf`): the IAM
  role's trust policy is scoped to `sts:AssumeRoleWithWebIdentity` from one
  named OIDC provider, with `StringEquals` conditions pinning both the
  `sub` (exact namespace/ServiceAccount) and `aud` (`sts.amazonaws.com`).
  A pod in a different namespace, or any caller without a valid projected
  token, cannot assume the role.
- **Entra Workload ID on AKS** (`terraform/modules/identity-bindings/azure.tf`):
  the federated credential's `subject` is the exact
  `system:serviceaccount:<namespace>:<name>` string -- no
  `azuread_application_password`/client secret is ever created, matching
  the pattern `azure-aks-platform` already uses.
- **GKE Workload Identity** (`terraform/modules/identity-bindings/gcp.tf`):
  the Google service account grants `roles/iam.workloadIdentityUser` to
  exactly one `PROJECT_ID.svc.id.goog[namespace/name]` member, not a
  project-wide grant. No `google_service_account_key` is ever created,
  matching the pattern `gcp-ai-pharmacy-platform` already uses.
- **Hardened pod spec.** `runAsNonRoot: true`, `readOnlyRootFilesystem: true`,
  `allowPrivilegeEscalation: false`, all Linux capabilities dropped, and a
  `RuntimeDefault` seccomp profile -- identical in every cloud, since none
  of this is cloud-specific.
- **ArgoCD AppProject scoping** (`argocd/project.yaml`): one allowed source
  repo, one Helm path, an empty `clusterResourceWhitelist`, and
  `destinations` named per cluster -- a misconfigured Application for one
  cloud cannot reach a cluster-scoped resource or a different repo.
