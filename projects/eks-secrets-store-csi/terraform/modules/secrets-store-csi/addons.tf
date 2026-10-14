# The Secrets Store CSI Driver and the AWS provider (ASCP) as one EKS managed
# add-on. EKS owns the DaemonSets, the CSIDriver object (including the
# tokenRequests ASCP needs for Pod Identity) and upgrades.
#
# configuration_values follows the add-on's schema, which nests the upstream
# driver chart's values under "secrets-store-csi-driver". Check it against
# `aws eks describe-addon-configuration --addon-name
# aws-secrets-store-csi-driver-provider --addon-version <v>` when pinning a
# version (docs/operations.md, "Before the first apply").

resource "aws_eks_addon" "pod_identity_agent" {
  count = var.manage_pod_identity_agent_addon ? 1 : 0

  cluster_name                = var.cluster_name
  addon_name                  = "eks-pod-identity-agent"
  addon_version               = var.pod_identity_agent_addon_version
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"
  tags                        = var.tags
}

locals {
  csi_addon_configuration = {
    "secrets-store-csi-driver" = {
      syncSecret = {
        enabled = var.sync_secret_enabled
      }
      enableSecretRotation = var.enable_secret_rotation
      rotationPollInterval = var.rotation_poll_interval
    }
  }
}

resource "aws_eks_addon" "secrets_store_csi" {
  cluster_name                = var.cluster_name
  addon_name                  = "aws-secrets-store-csi-driver-provider"
  addon_version               = var.csi_addon_version
  configuration_values        = jsonencode(local.csi_addon_configuration)
  resolve_conflicts_on_create = "OVERWRITE"
  # Keep in-cluster edits visible as drift instead of silently reverting them.
  resolve_conflicts_on_update = "PRESERVE"
  tags                        = var.tags

  depends_on = [aws_eks_addon.pod_identity_agent]
}
