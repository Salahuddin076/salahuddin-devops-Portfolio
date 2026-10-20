# 0002: Separate Terraform state per boundary in a real deployment

## Status

Accepted (documented for the real-deployment path; not applicable to this
repository's validate-only `examples/reference`, which intentionally wires
everything into one root so `terraform validate` exercises the whole graph
in one pass).

## Context

`terraform/examples/reference` puts the VPC, both segmentation zones, and
connectivity into a single root module. That's convenient for validation
but would be the wrong shape to actually operate: a change to the EKS node
group's security group rules should never be able to put the VPN
connection's Terraform state at risk, and vice versa.

## Decision

In a real deployment, split state along the same boundaries this project
treats as the security boundary:

1. **Connectivity** (`modules/connectivity`) -- changes rarely, high blast
   radius if broken (loses the entire hybrid link). Its own state, its own
   apply approval gate.
2. **Segmentation** (`modules/segmentation`, one instance per zone) --
   changes more often as new flows are added; still reviewed against the
   "no `0.0.0.0/0` in the regulated zone" rule before merge.
3. **Workload Terraform** (EKS, RDS -- see `../aws-multi-region-eks-dr`,
   `../aws-landing-zone`) -- changes most often, consumes the security
   group IDs and route tables the above two produce as remote-state
   outputs or SSM parameters, never raw resource blocks.

## Consequences

- A broken `terraform apply` in the workload layer cannot corrupt the
  connectivity or segmentation state.
- Cross-root wiring (e.g. "pass `module.edge_zone.security_group_id` to the
  EKS node group") becomes a `data` lookup or a remote-state read instead of
  a module reference, which also removes any risk of the module-dependency
  cycle this project's single-root example had to avoid explicitly (see
  `tests/test_terraform_static.py::ReferenceRootTests` for the regression
  test that caught it during development).
- This repository keeps the single-root example because splitting state
  three ways here would add directories and remote-state plumbing with no
  real backend to point them at, for no validation benefit.
