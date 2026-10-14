module "delivery" {
  source = "../../modules/container-delivery"

  name_prefix        = "delivery-demo"
  repository_full_id = var.repository_full_id
  branch             = "main"
  project_dir        = "projects/aws-codepipeline-container-delivery"
  trigger_file_paths = ["projects/aws-codepipeline-container-delivery/**"]

  vpc_id     = var.vpc_id
  subnet_ids = var.subnet_ids

  environments = {
    staging = { cpu = 256, memory = 512, desired_count = var.first_apply ? 0 : 1 }
    prod    = { cpu = 256, memory = 512, desired_count = var.first_apply ? 0 : 2 }
  }

  approval_emails    = var.approval_emails
  log_retention_days = 30

  tags = {
    cost-center = "platform-delivery"
  }
}
