# Operations

## Deploying the chart by hand (per cloud)

```sh
helm install portable-service helm/portable-service -f helm/portable-service/values-eks.yaml --namespace portable-service --create-namespace
helm install portable-service helm/portable-service -f helm/portable-service/values-aks.yaml --namespace portable-service --create-namespace
helm install portable-service helm/portable-service -f helm/portable-service/values-gke.yaml --namespace portable-service --create-namespace
```

Only the `-f` overlay changes between clouds; the chart, release name and
namespace do not.

## Deploying through ArgoCD (the actual "one deployment model")

1. Register each real cluster with ArgoCD under the name used in
   `argocd/applicationset.yaml`'s `clusterName`/`clusterServer`
   (`argocd cluster add <context>` against each cluster's kubeconfig context,
   or your platform's declarative cluster-secret equivalent).
2. Apply `argocd/project.yaml`, then `argocd/applicationset.yaml`.
3. The ApplicationSet's `list` generator fans out into three Applications
   (`portable-service-eks`, `portable-service-aks`, `portable-service-gke`),
   each pointing at the same chart path with a different `valueFiles` entry
   and `destination.name`.

## Applying the identity Terraform

This module is validated, never applied, in this repository (see the
top-level `CLAUDE.md`: no `terraform apply`/`plan` against a real account).
In a real rollout:

```sh
export TF_PLUGIN_CACHE_DIR=~/.terraform.d/plugin-cache
terraform -chdir=terraform/examples/reference init
terraform -chdir=terraform/examples/reference apply \
  -var="azure_subscription_id=<real-subscription>" \
  -var="azure_tenant_id=<real-tenant>" \
  -var="gcp_project_id=<real-project>"
```

Then copy the three outputs into the matching values overlay:

```sh
terraform -chdir=terraform/examples/reference output -raw aws_role_arn
terraform -chdir=terraform/examples/reference output -raw azure_client_id
terraform -chdir=terraform/examples/reference output -raw gcp_service_account_email
```

Each one replaces the synthetic placeholder in `values-eks.yaml` /
`values-aks.yaml` / `values-gke.yaml` respectively. The EKS module's
`aws_oidc_provider_arn`/`aws_oidc_provider_url` and the AKS module's
`azure_oidc_issuer_url` must also be set from the real cluster (its IAM OIDC
provider / its AKS OIDC issuer URL) before `apply` -- they are not
discoverable from this module alone, since it deliberately does not create
the clusters (see `docs/decisions/0001-identity-bindings-not-three-more-clusters.md`).

## Rendering the comparison table

```sh
python3 scripts/render_comparison.py docs/comparison.yaml
```

Fails loudly (non-zero exit, no output) if a cloud or a dimension's value is
missing -- see `tests/test_comparison.py`.
