# Azure AKS Enterprise Platform

Reference architecture -- synthetic, never deployed, no real Azure subscription, tenant or Azure DevOps organization used.

A reference AKS platform: hub-and-spoke networking, private AKS, Azure Container Registry, Key Vault through the CSI driver with Microsoft Entra Workload ID, and Azure DevOps pipelines. The website's project page classifies this as "reference" evidence -- it draws on Azure skills listed on the CV (AKS, Azure DevOps, Key Vault, Entra ID) but is explicitly not presented as a production deployment. Nothing here has ever been applied against a real Azure subscription.

## Problem

Teams moving to AKS often start with a public cluster, admin credentials in pipelines and secrets in Kubernetes objects. Each of those is individually convenient to stand up and individually expensive to unwind later: a public API server needs a retrofit to go private, a pipeline built around a service-principal secret needs every consumer updated when the credential-rotation pattern changes, and secrets baked into `ConfigMap`/`Secret` objects or environment variables need every workload's deployment manifest rewritten to move to a real secret store.

## Solution

- **Private AKS in a spoke VNet**, with egress forced through a hub firewall rather than a per-spoke NAT gateway -- one shared choke point to filter and log, not N of them.
- **Workload identity federation for both pods and pipelines.** A pod's projected ServiceAccount token and an Azure DevOps pipeline's run token are both exchanged for short-lived Entra tokens through a federated credential -- no client secret is minted for either.
- **Key Vault as the only secret store**, reached through the Secrets Store CSI driver over a private endpoint, authorized by Azure RBAC rather than vault access policies.

## Architecture

See `docs/architecture.md` for the full diagrams. In short: Hub VNet (Azure Firewall for egress control, Bastion) -> Spoke VNet (private AKS with system + user + spot pools, private endpoints for ACR and Key Vault) -> Platform services (ACR, Key Vault with CSI driver, Log Analytics) -> Delivery (Azure DevOps with workload identity federation).

Each Terraform module (`hub`, `spoke`, `aks`, `platform`, `workload-identity`, `pipeline-identity`) is designed to hold its own state in a real deployment; `terraform/examples/reference` wires all six into a single root purely so `terraform validate` can exercise the whole graph in one pass -- see `docs/decisions/0002-separate-state-per-root.md`.

## Security

- **Local accounts disabled on AKS.** `local_account_disabled = true`; every `kubectl` session authenticates as an Entra identity, authorized by **Azure RBAC for Kubernetes Authorization tied to Entra groups** (`azure_active_directory_role_based_access_control { managed = true, azure_rbac_enabled = true, admin_group_object_ids = [...] }`).
- **Azure Policy add-on** (`azure_policy_enabled = true`) enforces baseline pod security once the built-in initiative is assigned against a real tenant.
- **No client secrets in pipelines -- federated credentials only.** `azuread_application_password`/`azuread_service_principal_password` never appear in this repository (statically asserted by `tests/test_terraform_static.py`); both the pod workload identity and the Azure DevOps service connection authenticate through `azurerm_federated_identity_credential`/`azuread_application_federated_identity_credential`.
- **Private endpoints for ACR and Key Vault**, both with `public_network_access_enabled = false`, resolved by private DNS zones linked to the spoke VNet.
- See `docs/security.md` for the full list (private API server, Bastion-only operator access, explicit allow-listed firewall egress, RBAC-only Key Vault authorization).

## Reliability

- **Availability zones for node pools.** System, user and spot pools all set `zones = ["1", "2", "3"]`.
- **Separate system and user node pools.** The system pool runs `only_critical_addons_enabled = true` and nothing else, so an application workload can never starve a cluster add-on (or vice versa) for capacity -- the same separation principle used for the API/AI pool split in `gcp-ai-pharmacy-platform`, applied here to critical-addons/application instead of latency/batch.

## Cost (illustrative -- see `docs/cost.md`)

- **Azure Firewall is a significant fixed cost; share one hub across spokes.** It's the single largest fixed line item in this reference's illustrative sizing -- larger than the cluster's own compute -- which is exactly why the `hub` module has no spoke-count parameter: it's built once and peered to by every spoke.
- **Spot node pools for interruptible workloads.** The `spot` pool (`priority = "Spot"`, `min_count = 0`) costs nothing idle and runs at a steep discount when it does scale up, for workloads that can tolerate eviction.

## Results (illustrative)

Because this is a synthetic reference that has never been deployed, there is no production traffic graph or bill to show. The illustrative claim this pattern is built to support: centralizing egress in one shared hub firewall and eliminating standing credentials (local AKS accounts, service-principal secrets) removes two of the most common findings in an AKS security review -- a public cluster and a leaked pipeline secret -- without needing a NAT gateway or a secret-rotation job per spoke.

## Limitations

- Never applied against a real Azure subscription; there is no `terraform plan` output, only `validate`, in this repository's CI and in this README.
- `terraform/examples/reference` wires all modules into one root for validation convenience; a real deployment should split each module into its own state/backend (see `docs/decisions/0002-separate-state-per-root.md`).
- The Azure DevOps side of `pipeline-identity` (creating the project and the "workload identity federation" service connection itself) is outside Terraform's reach without the Azure DevOps provider, which this project does not add -- `docs/operations.md` documents the bootstrapping order instead of automating it end-to-end.
- The Helm chart (`helm/keyvault-csi-demo`) demonstrates the `SecretProviderClass` + workload identity wiring for one example workload (`payments-api`); it is a reference/demo chart, not a production application.
- `kubeconform` has no bundled schema for the Secrets Store CSI driver's `SecretProviderClass` CRD; CI resolves it from the community CRD catalog (`datreeio/CRDs-catalog`) rather than skipping that resource, the same approach the sibling `eks-secrets-store-csi` project uses for its CRD.
- Azure Firewall's application rule collection in `terraform/modules/hub` lists a small, illustrative set of AKS-required FQDNs, not Microsoft's full published "AKS egress" FQDN list.

## Lessons

- Private clusters need a plan for how CI reaches the API server before you create them. This reference's answer is Azure DevOps agents running inside the spoke (or peered to it) and Bastion for interactive operator access -- a hosted Microsoft-managed agent pool with no network path into the spoke simply cannot reach a private API server's endpoint, no credential fixes that.
- `outbound_type = "userDefinedRouting"` and forced tunneling are a package deal, not two independent choices: AKS validates that *something* supplies a default route for the subnet at cluster-create time, and refuses to create its own when told the outbound type is user-defined. Get the route table's `next_hop_in_ip_address` wrong (or create it after the cluster instead of before) and the cluster fails to provision, not fails at runtime -- `terraform validate` can't catch this class of ordering mistake, only a real apply can, which is exactly why this reference documents the dependency explicitly (`aks` module takes `route_table_id` as an input and grants its own identity `Network Contributor` on it before cluster creation) rather than leaving it implicit.
- A federated credential's `subject` has two independent authors who must agree on the exact string: the Terraform side (`system:serviceaccount:<ns>:<name>` or `sc://<org>/<project>/<connection>`) and the consumer side (the pod's actual ServiceAccount name/namespace, or the Azure DevOps service connection's actual GUIDs). Neither `terraform validate` nor `helm template`/`kubeconform` can catch a mismatch between the two -- it fails at token-exchange time with an opaque AADSTS70021, which is why `tests/test_terraform_static.py` and `tests/test_helm_static.py` both assert on the exact subject/annotation shape independently, the same lesson `gcp-ai-pharmacy-platform` drew from the equivalent GCP Workload Identity binding.

## Repository layout

```
terraform/
  modules/
    hub/                 # hub VNet, Azure Firewall + policy, Bastion
    spoke/                # spoke VNet, forced-tunneling route table, private-endpoints subnet, peering
    aks/                   # private AKS cluster, Azure RBAC, system/user/spot node pools
    platform/               # ACR, Key Vault, private endpoints + DNS zones, Log Analytics
    workload-identity/       # per-pod federated identity credentials (Entra Workload ID)
    pipeline-identity/        # Azure DevOps service-connection federated identity credential
  examples/
    reference/                 # wires all modules into one root (validation only)
helm/
  keyvault-csi-demo/             # SecretProviderClass + Deployment demonstrating the CSI driver + Workload ID
tests/
  test_terraform_static.py         # static assertions on every .tf file
  test_helm_static.py               # static assertions on the chart source
  test_readme.py                     # keeps this file's claims honest
```

## Validation

```text
$ python3 -m unittest discover -s tests -v
...
----------------------------------------------------------------------
Ran 46 tests in 0.013s

OK
```

```text
$ terraform fmt -check -recursive terraform
(no output -- already formatted)
```

```text
$ export TF_PLUGIN_CACHE_DIR=~/.terraform.d/plugin-cache
$ for d in terraform/modules/* terraform/examples/reference; do
    terraform -chdir="$d" init -backend=false -input=false && terraform -chdir="$d" validate
  done
Success! The configuration is valid.
(repeated for every module and the example root)
```

```text
$ helm lint helm/keyvault-csi-demo
==> Linting helm/keyvault-csi-demo
[INFO] Chart.yaml: icon is recommended

1 chart(s) linted, 0 chart(s) failed
```

```text
$ helm template payments-api helm/keyvault-csi-demo --namespace payments \
    | kubeconform -strict -summary -kubernetes-version 1.34.0 \
        -schema-location default \
        -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
Summary: 4 resources found parsing stdin - Valid: 4, Invalid: 0, Errors: 0, Skipped: 0
```

See `docs/operations.md` for the full command list and `docs/security.md` / `docs/architecture.md` for the design rationale.
