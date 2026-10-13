module "cost_guardrails" {
  source = "../../modules/cost-guardrails"

  name_prefix                  = "finops-demo"
  monthly_budget_usd           = var.monthly_budget_usd
  actual_thresholds_pct        = [50, 80, 100]
  forecast_thresholds_pct      = [100]
  notification_emails          = var.notification_emails
  anomaly_impact_threshold_usd = 100
  export_retention_days        = 400

  tags = {
    cost-center = "shared-platform"
  }
}
