# n8n's AWS dependencies next to an existing EKS cluster: Valkey for the
# queue, RDS PostgreSQL for state, three secrets without values, and Pod
# Identity roles for n8n and the KEDA operator. KEDA itself and the chart are
# installed with helm (docs/operations.md, "Install").

module "n8n_platform" {
  source = "../../modules/n8n-platform"

  name            = "n8n-${var.environment}"
  cluster_name    = var.cluster_name
  vpc_id          = var.vpc_id
  data_subnet_ids = var.data_subnet_ids

  # KEDA's operator runs without a pod security group, so it reaches Redis
  # through the node security group.
  additional_client_security_group_ids = [var.node_security_group_id]

  cache_multi_az           = true
  redis_auth_token_version = 1

  db_instance_class        = "db.t4g.medium"
  db_multi_az              = true
  db_backup_retention_days = 14

  namespace       = "n8n"
  service_account = "n8n"

  tags = {
    CostCenter = "automation"
  }
}
