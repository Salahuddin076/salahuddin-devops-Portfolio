# Shared platform: the ECR repository and the ECS cluster. Apply this root
# first; dev, staging and prod look both up by name. Each environment owns
# its ALB (docs/decisions/0004-alb-per-environment.md).
module "platform" {
  source = "../../modules/shared-platform"

  name_prefix = var.name_prefix
}
