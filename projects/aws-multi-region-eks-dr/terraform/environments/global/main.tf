# Cross-region data layer: Aurora Global Database, S3 CRR, the replicated
# database secret, and Route 53 failover. Applied after environments/primary
# and environments/dr (it needs their KMS keys, subnet groups and security
# groups), then again after both charts are installed (phase 2: ALB names).

module "global_data" {
  source = "../../modules/global-data"
  providers = {
    aws.primary = aws.primary
    aws.dr      = aws.dr
  }

  name    = var.app_name
  primary = var.primary
  dr      = var.dr

  aurora_engine_version  = var.aurora_engine_version
  aurora_instance_class  = var.aurora_instance_class
  primary_instance_count = var.primary_instance_count
  dr_instance_count      = var.dr_instance_count
  db_password_version    = var.db_password_version

  primary_bucket_name         = "example-${var.app_name}-data-${var.primary_region}"
  dr_bucket_name              = "example-${var.app_name}-data-${var.dr_region}"
  s3_replication_time_control = var.s3_replication_time_control

  secret_name = "${var.app_name}/aurora-master"
  dns         = var.dns

  replication_lag_alarm_seconds = var.replication_lag_alarm_seconds
  alarm_topic_arns              = var.alarm_topic_arns
}
