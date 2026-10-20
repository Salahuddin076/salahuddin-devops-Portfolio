# Wires the single identity-bindings module -- its whole job is to show the
# AWS/Azure/GCP identity resource sets side by side, bound to the SAME
# ServiceAccount name/namespace that helm/portable-service's serviceaccount.yaml
# renders in every cluster. This repo deliberately does not rebuild three full
# EKS/AKS/GKE cluster stacks here -- those already exist as
# aws-multi-region-eks-dr, azure-aks-platform and gcp-ai-pharmacy-platform; see
# docs/decisions/0001-identity-bindings-not-three-more-clusters.md.

module "identity_bindings" {
  source = "../../modules/identity-bindings"

  gcp_project_id = var.gcp_project_id
}
