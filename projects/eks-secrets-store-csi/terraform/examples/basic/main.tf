# Zero hard-coded secrets for one app on an existing EKS cluster: the
# Secrets Store CSI Driver + ASCP add-on, two CMK-encrypted secrets (no
# values), and a Pod Identity role scoped to them.

module "secrets_store_csi" {
  source = "../../modules/secrets-store-csi"

  name         = "secure-frontend-${var.environment}"
  cluster_name = var.cluster_name

  # The cluster stack (projects/aws-multi-region-eks-dr) already installs the
  # Pod Identity agent.
  manage_pod_identity_agent_addon = false

  sync_secret_enabled    = false
  enable_secret_rotation = true
  rotation_poll_interval = "2m"

  db_secret_name      = "secure-frontend/${var.environment}/db-credentials"
  api_key_secret_name = "secure-frontend/${var.environment}/api-key"
  rotation_lambda_arn = var.rotation_lambda_arn
  rotation_days       = 30

  namespace       = "web"
  service_account = "secure-frontend"

  tags = {
    CostCenter = "frontend"
  }
}
