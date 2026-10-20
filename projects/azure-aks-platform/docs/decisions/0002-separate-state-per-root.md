# 0002: Separate Terraform state per layer

## Status

Accepted (documented, not enforced by backend config in this reference -- see Consequences).

## Context

This project has layers with very different change frequency and blast radius: the hub (rarely changes once the firewall policy is set), the spoke (changes when a new workload needs a subnet), the AKS cluster (changes on upgrades and node-pool resizing), platform services (ACR/Key Vault/Log Analytics, changes rarely), and the two identity modules (change whenever a new workload or pipeline is onboarded, which should be frequent and low-risk). A single Terraform state covering all of them means every `plan` diffs the whole graph, and a mistake applying a node-pool resize risks touching the hub firewall's state in the same operation.

## Decision

Each of `hub`, `spoke`, `aks`, `platform`, `workload-identity` and `pipeline-identity` is its own Terraform module with its own `versions.tf`/`variables.tf`/`outputs.tf`, designed to be instantiated as its own root module with its own backend/state in a real deployment, wired together by passing one layer's outputs as the next layer's variables (e.g. `module.hub.firewall_private_ip` into `spoke`, `module.spoke.aks_subnet_id` into `aks`).

## Consequences

- `terraform/examples/reference` instantiates all six modules in a single root. That's deliberate for this repository: the whole point of the example is for `terraform validate` to exercise the full dependency graph in one pass during code review, without needing per-layer `terraform_remote_state` data sources that would require a real backend to resolve. It is explicitly *not* the recommended production layout -- see the `README.md` Limitations section.
- A production deployment following this pattern needs a `terraform_remote_state` data source (or equivalent, e.g. Terragrunt) at each layer boundary, since there's no longer a single `module` block passing values in Terraform-native form.
- `platform` and `aks` have a real, deliberate non-dependency: `platform`'s Log Analytics workspace feeds `aks` (Container Insights), while `aks`'s kubelet/CSI-driver identities would otherwise feed back into `platform` for role assignments. Those role assignments are granted from the example root instead of from either module, specifically to avoid a two-module cycle that `terraform validate` rejects outright -- see `tests/test_terraform_static.py::test_platform_module_does_not_depend_on_aks_module_outputs`.
- `workload-identity` and `pipeline-identity` are the most-likely-to-change layers (one onboarding per new workload or pipeline) and are also the lowest-blast-radius: a mistake there can misconfigure one workload's Key Vault access, never the network or the cluster itself.
