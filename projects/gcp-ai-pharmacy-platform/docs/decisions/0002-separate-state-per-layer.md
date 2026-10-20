# 0002: Separate Terraform state per layer

## Status

Accepted (documented, not enforced by backend config in this reference — see Consequences).

## Context

This project has four layers with very different change frequency and blast radius: the network (rarely changes once laid out), the GKE cluster (changes on upgrades and node-pool resizing), the database (changes rarely, and a mistake is the hardest to recover from), and secrets/delivery (changes often, as part of normal CI/CD). A single Terraform state covering all of them means every `plan` diffs the whole graph, and a bad apply to one layer can't be isolated from the others' state.

## Decision

Each of `network`, `gke-cluster`, `cloud-sql`, `secret-manager` and `delivery` is its own Terraform module with its own `versions.tf`/`variables.tf`/`outputs.tf`, designed to be instantiated as its own root module with its own backend/state in a real deployment, wired together by passing one layer's outputs as the next layer's variables (e.g. `module.network.network_id` into `gke-cluster` and `cloud-sql`).

## Consequences

- `terraform/examples/reference` instantiates all six modules (including `project-apis`) in a single root. That's deliberate for this repository: the whole point of the example is for `terraform validate` to exercise the full dependency graph in one pass during code review, without needing five separate `terraform init`/`validate` invocations wired through `terraform_remote_state` data sources that would require a real backend to resolve. It is explicitly *not* the recommended production layout — see the `README.md` Limitations section.
- A production deployment following this pattern needs a `terraform_remote_state` data source (or equivalent, e.g. Terragrunt) at each layer boundary to read the previous layer's outputs, since there's no longer a single `module` block passing values in Terraform-native form.
- The database and secrets modules remain reusable by any other service's GKE layer, since they don't hardcode the cluster's name or node pool shape into their own variables.
