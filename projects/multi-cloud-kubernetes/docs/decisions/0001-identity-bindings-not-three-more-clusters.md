# 0001: One identity-bindings module, not three more cluster stacks

## Status

Accepted.

## Context

This repository already has a full, validated cluster stack for each of the
three clouds this project compares: `aws-multi-region-eks-dr` (EKS),
`azure-aks-platform` (AKS) and `gcp-ai-pharmacy-platform` (GKE). The task
this project is meant to demonstrate -- "the same Helm-packaged service
deployed to all three, with the platform-layer differences documented" --
does not need a fourth, fifth and sixth cluster stack to make its point; it
needs the workload layer (one chart) and the identity layer (how that
workload authenticates on each cloud) to be real, validated code, with the
cluster layer treated as already solved elsewhere in this portfolio.

## Decision

`terraform/modules/identity-bindings` creates only the IAM-side objects
needed to bind the portable Helm chart's ServiceAccount to a cloud identity
on each of the three clouds: one `aws_iam_role` (IRSA trust policy), one
`azurerm_user_assigned_identity` + `azurerm_federated_identity_credential`
(Entra Workload ID), and one `google_service_account` +
`google_service_account_iam_member` (GKE Workload Identity). It takes the
cluster's OIDC provider ARN/issuer URL as input variables rather than
creating a cluster to produce them.

## Consequences

- `terraform/examples/reference` validates against real `aws`, `azurerm` and
  `google` provider schemas in one root, proving the three resource sets are
  individually correct, without ever creating (or needing) a real cluster.
- A real rollout still needs one of the three cluster-stack projects (or an
  equivalent) to produce the OIDC provider/issuer values this module
  consumes -- `docs/operations.md` documents that handoff explicitly instead
  of pretending this module is self-sufficient.
- This project's Terraform surface is intentionally small. The interesting,
  testable claim here is "the same ServiceAccount name/namespace binds
  cleanly to all three identity mechanisms," not "here is a third copy of an
  EKS/AKS/GKE cluster module."
