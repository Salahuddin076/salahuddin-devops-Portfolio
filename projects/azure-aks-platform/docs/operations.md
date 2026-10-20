# Operations

## Running the checks locally

```sh
cd projects/azure-aks-platform

# Python static tests (stdlib unittest only, no network, no cloud calls)
python3 -m unittest discover -s tests -v

# Terraform formatting + per-directory validation
export TF_PLUGIN_CACHE_DIR=~/.terraform.d/plugin-cache
terraform fmt -check -recursive terraform
for d in terraform/modules/* terraform/examples/reference; do
  terraform -chdir="$d" init -backend=false -input=false
  terraform -chdir="$d" validate
done

# Helm
helm lint helm/keyvault-csi-demo
helm template payments-api helm/keyvault-csi-demo --namespace payments \
  | kubeconform -strict -summary -kubernetes-version 1.34.0 \
      -schema-location default \
      -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
```

`terraform plan`/`apply`/`destroy` and any `az` CLI call are never run against this configuration -- see the repository-wide `CLAUDE.md` rule. `terraform validate` is sufficient to catch provider-schema errors (wrong argument name, wrong type, missing required block) without needing a real Azure subscription or tenant.

## Why kubeconform needs the CRD catalog, not `-skip`

`SecretProviderClass` (`secrets-store.csi.x-k8s.io/v1`) is a CRD kubeconform's bundled Kubernetes schemas don't know about. The sibling AWS project (`eks-secrets-store-csi`) hit the same gap and resolved it by pointing kubeconform at the community CRD schema catalog (`datreeio/CRDs-catalog`) with a second `-schema-location`, rather than `-skip`-ing the resource out of validation entirely -- `-skip` would mean the one CRD manifest in this chart is never actually schema-checked. This project follows the same approach for consistency and because the alternative throws away real coverage.

## Bootstrapping order for the Azure DevOps pipeline identity (reference only, never actually run)

`terraform/modules/pipeline-identity` needs `ado_project_id` and `ado_service_connection_id` as inputs -- both are GUIDs Azure DevOps assigns when a project and a "workload identity federation" type service connection are created, which happens on the Azure DevOps side, not in this Terraform. The real order is:

1. Create (or identify) the Azure DevOps project; note its project ID.
2. Create an empty "workload identity federation" service connection in that project (ADO generates its GUID and a `subject` value even before an Entra app exists to trust it).
3. Apply `module.pipeline_identity` with those two IDs as variables -- this creates the Entra app registration, service principal, and the federated credential trusting that exact subject.
4. Paste the resulting `application_client_id` output back into the Azure DevOps service connection's configuration.

No step in this sequence ever mints a client secret.

## Verifying a pod's workload identity after a (hypothetical) deploy

```sh
kubectl get sa payments-api -n payments \
  -o jsonpath='{.metadata.annotations.azure\.workload\.identity/client-id}'
# must equal module.workload_identity.client_ids["payments-api"], and that
# client ID's federated credential subject must equal
# system:serviceaccount:payments:payments-api exactly.
```

## Scale-to-zero / spot behavior

The spot node pool's `min_count = 0` means the cluster autoscaler can remove every node in that pool when nothing is scheduled onto it (via the `kubernetes.azure.com/scalesetpriority=spot:NoSchedule` taint + a matching toleration on interruptible workloads). Nothing in this project automates a schedule (e.g. a CronJob scaling a Deployment to 0 outside business hours) -- the infrastructure supports it, wiring a schedule is left to the application/platform team, same scoping decision made in `gcp-ai-pharmacy-platform`.
